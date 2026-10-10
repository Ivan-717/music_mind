"""给「未入库的文本艺人」查 Wikidata 的流派/地区 —— 画像那半边的补充。

跑法：cd agent-service && .venv/Scripts/python.exe fetch_artist_wikidata.py
输出：agent-service/.data/wikidata_artists.json
      （画像读缓存，不每次打网）
      【可中断续跑】逐条落盘，中断后重跑自动跳过已查的（v2 格式缓存）

【验证规则：必须「像是音乐人」才采纳】按名字搜到实体后，描述里要含
歌手 / 乐队 / 音乐 / 唱作 / 说唱 / rapper / singer / musician / band 之类的词。
实测「队长」直接搜到的是「足球队长」——不验证就会把球队写进你的画像。
【宁可少补，不可错补】搜不到 / 验证不过 → 不填 —— 画像就不提这个人，
而不是猜一个。这是对齐层同一条哲学。

【覆盖率预期】实测中文说唱的新艺人多数没有维基条目（h3R3 搜不到），
主流的（郑润泽/颜人中）有 —— 能补一半上下，流派维度部分覆盖，仍值得。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from musicmind_agent.config import PROJECT_ROOT  # noqa: E402
from musicmind_agent.db import get_connection  # noqa: E402
from musicmind_agent.validate.normalize import name_key  # noqa: E402

OUT = PROJECT_ROOT / "agent-service" / ".data" / "wikidata_artists.json"
API = "https://www.wikidata.org/w/api.php"
SLEEP = 1.5        # 0.3 实测跑到一半开始被 429；0.8 在密集请求之后第 2 个请求就卡死 ——
                   # 匿名 IP 的限额是滑动窗口，打满后短退避退不下来。1.5s ≈ 40 req/min

# 「像是音乐人」的判据（中英都看）。宁可窄一点 —— 挡住球队队长、地名、影视角色。
# 【「艺人/藝人」要收】实测鹿晗的描述是「中國男藝人」——不收会漏掉一整类
# 【「團體/組合」要收】实测 2PM 正主的描述是「南韓男子偶像團體」——不收会漏掉
# 整个偶像团体类；更糟的是正主被跳过之后，「2PM音樂作品列表」的英文描述
# "Wikimedia band discography" 恰好含 band，就被当成音乐人收进来了。
MUSIC_WORDS = ("歌手", "乐队", "音乐", "唱作", "说唱", "嘻哈", "饒舌", "饶舌",
               "艺人", "藝人", "藝员", "團體", "团体", "組合", "组合",
               "乐坛", "樂壇",
               "rapper", "singer", "musician", "band", "songwriter", "vocalist", "DJ")

# 「肯定不是音乐人」的排除词，命中即拒、优先级高于包含词。
# 【为什么必须显式排除】「作品列表」类条目的描述里常有 band/discography 这种词，
# 靠包含词挡不住（见上）。实测案例：2PM音樂作品列表 / BIGBANG音樂作品列表。
# 【「的专辑」不写成裸「专辑」】艺人描述里可能出现「专辑制作人」——裸词会误拒真人。
# 【「守护人/主保」】实测搜「cecilia」命中「聖則濟利亞」——desc「基督教的音乐守护人」
# 里的「音乐」混过了包含词。是宗教人物，不是艺人。
# 【「维基百科/wikipedia」】实测搜「C-BLOCK」：长沙组（desc=中国嘻哈乐队）排在
# 德国同名组合后面，而德国那条的 desc 是垃圾文本「乐队（不要讲本页链接至中文
# 维基百科）」——desc 里出现「维基百科」字样就是被破坏/自我指涉的描述，不可信。
REJECT_WORDS = ("列表", "list", "discography", "維基媒體", "wikimedia",
                "维基百科", "wikipedia", "的专辑", "的專輯", "album",
                "守护人", "守護人", "主保")


def _get(session, params: dict, tries: int = 4):
    """带退避的 GET。

    【为什么不能裸 try/except 吞掉】第一版把请求异常和「没搜到」混成一个 None ——
    跑了几百个开始被限流（429）后，**后半段全部被静默判成「没有音乐人条目」**
    （实测 464 个只「查到」15 个，而马思唯这种明明在的也「没有」）。
    限流是**可重试的临时故障**，和「上游真没有」是两回事 —— 退避重试，
    真不行就抛出来让整轮中止（已查的逐条落盘，重跑续上）。

    【退避为什么是 15/30/60/120s】5/10/15s 实测退不下来 —— 滑动窗口一旦打满，
    等待时间远长于单次退避。优先听上游的 Retry-After，没有再用指数退避。
    """
    for i in range(tries):
        try:
            r = session.get(API, params=params, timeout=15)
        except requests.exceptions.RequestException:
            # 【网络超时是 429 的同类，不是致命错误】实测一次 ReadTimeout 把 122 条
            # 的重查整轮带走 —— 请求层的临时故障都要退避重试，不能冒泡杀进程。
            time.sleep(5 * (2 ** i))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            wait = int(r.headers.get("Retry-After") or 0) or 15 * (2 ** i)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Wikidata 连续 {tries} 次失败（限流/网络没恢复，稍后重跑）")


def collect_names(connection) -> list[str]:
    """所有用户的「未入库」曲目里的主艺人名（去重、归一）。"""
    with connection.cursor() as cur:
        cur.execute(
            """SELECT artists FROM user_playlist_track
               WHERE user_removed = 0 AND match_status <> 'MATCHED'"""
        )
        rows = cur.fetchall()
    seen: dict[str, str] = {}          # name_key → 展示用原名
    for r in rows:
        primary = (r["artists"] or "").split(" / ")[0].strip()
        if primary:
            seen.setdefault(name_key(primary), primary)
    return sorted(seen.values())


def _anchor(text: str) -> str:
    """锚定用的名字形：name_key（去空格/小写/剥括号/繁转简）之上再去间隔点。"""
    return name_key(text).replace("·", "")


def search_entity(session, name: str) -> dict | None:
    """搜实体 + 名字锚定 + 描述验证。返回 {qid, label, desc} 或 None（= 真没有）。

    请求层的异常由 _get 重试/抛出 —— 这里的 None 只表示「搜过了，没有」。
    """
    r = _get(session, {
        "action": "wbsearchentities", "search": name, "language": "zh",
        "uselang": "zh", "format": "json", "limit": 5})
    want = _anchor(name)
    for h in r.json().get("search", []):
        desc = (h.get("description") or "")
        # label 也要查排除词：实测「2PM錄像作品列表」的 desc 是空的，靠 label 才挡得住
        if any(w.lower() in (desc + " " + (h.get("label") or "")).lower()
               for w in REJECT_WORDS):
            continue
        # 【名字锚定】match.text 是「它为什么被搜出来」的那段文本，归一后必须与
        # 输入相等。不锚定的话，正主被前两道闸拒掉后，模糊匹配的噪声会顺位上桌：
        # 实测搜「李玟」，正主（desc=已故華語樂壇天后）被跳过，「李玟暎」
        # （match.text='李玟暎'）顶上 —— 张冠李戴。宁可这次不补，不可补错人。
        m = h.get("match") or {}
        if _anchor(m.get("text") or h.get("label") or "") != want:
            continue
        # 描述里命中音乐人关键词才算 —— 搜「队长」的第一个结果是足球队长
        if any(w.lower() in desc.lower() for w in MUSIC_WORDS):
            return {"qid": h["id"], "label": h.get("label") or name, "desc": desc}
    return None


def fetch_claims(session, qid: str) -> tuple[list[str], list[str], dict]:
    """拿 P136 流派 / 地区（Q-id 列表）。顺带把搜索没给的完整信息带回来。

    【地区要 P27+P495 两处】P27（国籍）只有「人」有 —— 实测 2PM/BIGBANG 的 P27
    都是 0，韩国团体会集体缺地区。团体的地区信号在 P495（country of origin）。
    """
    r = _get(session, {
        "action": "wbgetentities", "ids": qid,
        "props": "claims|descriptions", "languages": "zh|en", "format": "json"})
    e = r.json()["entities"][qid]
    claims = e.get("claims", {})

    def qids(pid: str) -> list[str]:
        out = []
        for c in claims.get(pid, []):
            v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(v, dict) and v.get("id"):
                out.append(v["id"])
        return out

    return qids("P136"), qids("P27") + qids("P495"), e.get("descriptions", {})


def label_of(session, qids: list[str]) -> dict[str, str]:
    """批量拿 Q-id 的中文（退英文）label。分批请求。

    【为什么必须分批】第一版 `ids="|".join(qids[:50])` —— 传超过 50 个时
    超出的部分不是报错，是**静默丢失**（留在缓存里的就是裸 Q-id）。
    464 位艺人的 genre qid 去重后必然超 50，等于后半截全不解析。
    """
    out: dict[str, str] = {}
    for i in range(0, len(qids), 50):
        r = _get(session, {
            "action": "wbgetentities", "ids": "|".join(qids[i:i + 50]),
            "props": "labels", "languages": "zh|zh-hans|zh-hant|en", "format": "json"})
        for qid, e in r.json()["entities"].items():
            labels = e.get("labels", {})
            for lang in ("zh", "zh-hans", "zh-hant", "en"):
                if lang in labels:
                    out[qid] = labels[lang]["value"]
                    break
        time.sleep(SLEEP)
    return out


CACHE_V = 2   # 缓存格式版本。无版本号的旧缓存是限流 bug 时代的产物，一律重查


def load_cache() -> dict[str, dict]:
    """读上一轮缓存（只认 v2）。

    【为什么旧缓存不可信】旧的「没查到」可能是限流被吞出来的假阴性
    （马思唯那种明明在的也被判「没有」）—— 宁可重查，不能续用一个错的基线。
    """
    if not OUT.exists():
        return {}
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in old.items()
            if isinstance(v, dict) and v.get("v") == CACHE_V}


def main() -> int:
    connection = get_connection()
    names = collect_names(connection)
    connection.close()
    print(f"未入库艺人：{len(names)} 位（去重后）")

    session = requests.Session()
    session.headers.update({"User-Agent": "MusicMind/0.1 (personal learning project)"})

    result = load_cache()
    todo = [n for n in names if name_key(n) not in result]
    if len(todo) < len(names):
        print(f"沿用上轮缓存 {len(names) - len(todo)} 位，本轮待查 {len(todo)} 位")

    def save() -> None:
        """【为什么逐条落盘】上一版只在全部跑完后写一次 —— 464 位要跑十几分钟，
        中途任何中断（限流、Ctrl+C、上下文爆）整轮白跑。逐条写，重跑自动续上。"""
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                       encoding="utf-8")

    for i, name in enumerate(todo, 1):
        ent = search_entity(session, name)
        if ent is None:
            # 搜不到 or 搜到的都不是音乐人 —— 两种都不填（不猜）
            result[name_key(name)] = {"v": CACHE_V, "miss": True}
            print(f"  [{i}/{len(todo)}] {name} —— 没有可确认的音乐人条目")
            save()
            time.sleep(SLEEP)
            continue

        genres, countries, descs = fetch_claims(session, ent["qid"])
        result[name_key(name)] = {
            "v": CACHE_V,
            "qid": ent["qid"], "label": ent["label"], "desc": ent["desc"],
            "genres_qids": genres, "country_qids": countries,
            "desc_zh": (descs.get("zh", {}) or {}).get("value")
                or (descs.get("en", {}) or {}).get("value"),
        }
        print(f"  [{i}/{len(todo)}] {name} ✓ {ent['label']}（{ent['desc'][:24]}）")
        save()
        time.sleep(SLEEP)

    # Q-id → 真名，统一补回。每轮都全量重解析一遍 —— 顺带补上一轮中断在半路的。
    all_qids = sorted({q for v in result.values() if not v.get("miss")
                       for q in v["genres_qids"] + v["country_qids"]})
    labels = label_of(session, all_qids)
    for v in result.values():
        if v.get("miss"):
            continue
        v["genres"] = [labels.get(q, q) for q in v["genres_qids"]]
        v["country"] = [labels.get(q, q) for q in v["country_qids"]]
    save()

    hit = sum(1 for v in result.values() if not v.get("miss"))
    print(f"\n查到 {hit}/{len(names)} 位音乐人（其余：无音乐人条目）")
    print(f"缓存：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
