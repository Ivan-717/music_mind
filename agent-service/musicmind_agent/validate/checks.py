"""五层检查。每一层都往 result 里追加违规，不抛异常。

【为什么不抛】一次跑完收集所有问题，才能一次把完整的错误清单回灌给模型修。
一次只报一个错会让重写轮次爆炸（每次修一个，改完又冒一个）。
"""

from __future__ import annotations

import json
import re

from musicmind_agent.evidence import load_enriched
from musicmind_agent.render import PLACEHOLDER
from musicmind_agent.tools import ToolContext
from musicmind_agent.validate import ERROR, WARNING, ValidationResult
from musicmind_agent.validate.normalize import (
    canonical,
    extract_numbers,
    name_matches,
    name_variants,
    numeric_forms,
    parse_cn_number,
)

CN_NUMBER_RE = re.compile(
    r"(?<![\d.])([零一二两三四五六七八九十]+|一半|三分之一|四分之一|"
    r"[三四五六七八九]成|\d+(?:\.\d+)?%?)(?![\d.])"
)


# ============================================================
# 遍历报告的工具
# ============================================================

def walk_claims(report: dict):
    """产出 (路径, claim dict)。所有 claim 级的检查共用。"""
    for i, dim in enumerate(report.get("dimensions") or []):
        for j, claim in enumerate(dim.get("claims") or []):
            yield f"dimensions[{i}].claims[{j}]", claim


def walk_texts(report: dict):
    """产出 (路径, 文本)。所有文本级的检查共用 ——
    **必须覆盖每一个 LLM 写的字段**，漏一个就是一个洞。
    第一版就是漏了 limitations，于是那里面带着花括号原样输出了。"""
    head = report.get("headline") or {}
    yield "headline.title", head.get("title") or ""
    yield "headline.subtitle", head.get("subtitle") or ""

    for path, claim in walk_claims(report):
        yield f"{path}.text", claim.get("text") or ""

    for i, dim in enumerate(report.get("dimensions") or []):
        yield f"dimensions[{i}].summary", dim.get("summary") or ""

    for i, rec in enumerate(report.get("recommendations") or []):
        yield f"recommendations[{i}].reason", rec.get("reason") or ""
        rel = rec.get("relation_to_history") or {}
        yield f"recommendations[{i}].relation_to_history.note", rel.get("note") or ""

    for i, item in enumerate(report.get("limitations") or []):
        yield f"limitations[{i}]", item or ""


# ============================================================
# L1 结构层
# ============================================================

def check_structure(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """不解析的占位符、空口断言、引用不存在的事实。**一个字都不用查库。**"""

    # --- 未解析的占位符 ---
    # 渲染时 strict=False 会把解析不了的 key 原样留下。留下的原因只有一个：
    # 这个 key 不在 facts 仓里 —— 也就是模型**编了一个事实名**。
    # 实测样本：qwen 写了 mood.arousal_measured_median，
    # 而仓里只有 arousal_measured_mean/min/max 和 arousal_median。
    for path, text in walk_texts(report):
        result.checked += 1
        for match in PLACEHOLDER.finditer(text):
            key = match.group(1)
            result.violations.append(Violation_(
                "structure", path,
                f"引用了不存在的事实 {key!r}"
                + ("（键名看起来像两个真实键的拼接）" if _looks_stitched(key, ctx) else ""),
            ))

    # --- metric_ref 的 key 必须存在 ---
    for path, claim in walk_claims(report):
        for ref in claim.get("metric_refs") or []:
            key = ref.get("key")
            if key and key not in ctx.facts:
                result.violations.append(Violation_(
                    "structure", path, f"metric_ref 指向不存在的事实 {key!r}"))

        # --- 不许空口断言 ---
        # 每条 claim 要么引用了事实（有数字支撑），要么挂了证据（能指回歌），
        # 两者都没有就是「凭感觉说」，而原则 4 要求可解释。
        #
        # 【为什么是 ERROR 不是 WARNING】prompt 里「每条结论必须挂证据」是硬规则，
        # 而 WARNING 不阻断落库 —— 模型可以写一堆没证据的话，只要不报 error 就过了。
        # 实测这两份报告里合法 claim 有 0 条是「两者都没有」，
        # 所以升级的误伤成本是零，堵的却是一个真洞。
        # 方法的说明（「发行年不等于收听时间」这类）本来就不该写成 claim，
        # 它属于 limitations —— 打回去正好教会模型这一点。
        has_ref = bool(claim.get("metric_refs"))
        has_ev = bool(claim.get("evidence_track_ids"))
        result.checked += 1
        if not has_ref and not has_ev:
            result.violations.append(Violation_(
                "structure", path,
                "这条结论既没有引用事实也没有证据曲目。"
                "补充 {fact.key} 引用或 evidence_track_ids，"
                "或者如果它只是方法说明，移到 limitations"))

    # --- 核心维度必须齐全 ---
    # 核心维度固定是设计决定（两次运行才可比）。缺了要报警，但不阻断 ——
    # 模型偶尔漏一个不该让整份报告作废
    present = {d.get("dimension") for d in report.get("dimensions") or []}
    for required in ("genre", "era", "artist", "mood_energy"):
        result.checked += 1
        if required not in present:
            result.violations.append(Violation_(
                "structure", "dimensions", f"缺少核心维度 {required}", WARNING))


def _looks_stitched(key: str, ctx: ToolContext) -> bool:
    """这个不存在的 key 看起来是不是两个真实 key 拼出来的。

    写这条是为了让报错信息有用 —— 「引用了不存在的事实」和
    「你似乎把 A 和 B 拼在了一起」对模型的重写完全是两种提示。
    """
    parts = key.split(".")
    if len(parts) < 3:
        return False
    return any(f"{'.'.join(parts[:i])}.{'.'.join(parts[i:])}" != key
               and '.'.join(parts[:i]) in ctx.facts
               and '.'.join(parts[i:]) in ctx.facts
               for i in range(1, len(parts)))


def Violation_(layer, path, detail, severity=ERROR):
    from musicmind_agent.validate import Violation
    return Violation(layer=layer, path=path, detail=detail, severity=severity)


# ============================================================
# L2 引用层
# ============================================================

def check_references(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """metric_ref 里模型自己声明的 expect 值，和事实仓的实际值对得上吗。

    比「编数字」更隐蔽的一种错：**引用了真实存在的事实名，但读错了值**。
    实测样本：把 coverage.genre_ratio（89.5%，任一来源）当成专辑级的覆盖率
    （实际 31%），写出了自相矛盾的句子。
    """
    for path, claim in walk_claims(report):
        for ref in claim.get("metric_refs") or []:
            key = ref.get("key")
            expect = ref.get("expect")
            if key not in ctx.facts or expect is None:
                continue

            result.checked += 1
            actual = ctx.facts[key]
            tol = ref.get("tol", 0.005)

            if isinstance(actual, (int, float)) and isinstance(expect, (int, float)):
                if abs(float(actual) - float(expect)) > tol:
                    result.violations.append(Violation_(
                        "reference", path,
                        f"{key}：报告声明 {expect}，实际 {actual}（差超过 {tol}）"))
            elif actual != expect:
                result.violations.append(Violation_(
                    "reference", path, f"{key}：报告声明 {expect!r}，实际 {actual!r}"))


# ============================================================
# L3 字面量层
# ============================================================

def check_literals(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """叙事里的裸数字，必须能绑到某条事实、或某首证据曲目的年份/时长。

    为什么需要它：占位符机制堵死了「主动编数字」，但模型可能**忘了用占位符**
    而直接写「68.3%」。这种要被抓到 —— 要么改成引用，要么证明它确实对得上。

    中文数字（「三成」「两首」）也要归一化后一起判 ——
    只扫阿拉伯数字的话，换一种写法就绕过去了。
    """
    # 所有允许出现的数字形态
    allowed: set[str] = set()
    for value in ctx.facts.values():
        if isinstance(value, (int, float)):
            allowed |= numeric_forms(float(value))

    # 【事实的【键名】里带的数字也是合法的】年代桶就是这种情况：
    # 键是 `era.1995.share`，报告写「1995–1999 段占 0.9%」——
    # 1995 出现在键里，不在值里，不收进来的话每个年代桶都会误报一次。
    for key in ctx.facts:
        for token in re.findall(r"\d+", key):
            allowed.add(token)

    # 年代桶还要算上【结束年份】：键是 `era.1995.share`，报告写的是
    # 「1995–1999 段」—— 1999 = 1995 + 桶宽 - 1，它不出现在任何键或值里。
    # 桶宽从 `era.bucket_years` 读，不写死。
    try:
        bucket_width = int(ctx.facts.get("era.bucket_years", 5))
    except (TypeError, ValueError):
        bucket_width = 5
    for key in ctx.facts:
        match = re.match(r"era\.(\d{4})\.", key)
        if match:
            start = int(match.group(1))
            allowed.add(str(start + bucket_width - 1))

    # 方法描述里的常量。「30 秒音频」说的是分析窗口长度，
    # 不是关于用户数据的断言，但它确实会被字面量扫描抓到。
    # 与其写个正则去区分「方法描述」和「数据断言」（做不到可靠），
    # 不如把这个常量显式列出来 —— 它只有一个。
    allowed.add("30")

    # 证据曲目的年份和时长也是合法数字（「2016 年发行的《xxx》」）
    for track in ctx.tracks:
        if track.year:
            allowed.add(str(track.year))
        if track.duration_ms:
            allowed.add(str(track.duration_ms // 1000))
            allowed.add(f"{track.duration_ms // 60000}:{track.duration_ms // 1000 % 60:02d}")

    for path, text in walk_texts(report):
        cleaned = PLACEHOLDER.sub(" ", text)
        result.checked += 1
        for raw in CN_NUMBER_RE.findall(cleaned):
            token = raw
            if not token[0].isdigit():
                parsed = parse_cn_number(token)
                if parsed is None:
                    continue
                token = canonical(parsed)
            else:
                token = token.rstrip("%")
                if "%" in raw:
                    token = f"{float(token) / 100:.2f}"

            if token in allowed:
                continue
            # 允许四舍五入到整数后命中
            try:
                if f"{float(token):.0f}" in allowed or f"{float(token):.1f}" in allowed:
                    continue
            except ValueError:
                pass

            severity = literal_severity(raw)
            if severity is None:
                continue
            result.violations.append(Violation_(
                "literal", path, f"数字 {raw!r} 绑不到任何事实或证据", severity))


def literal_severity(raw: str) -> str | None:
    """绑不上的数字该判多重。返回 None 表示跳过。

    【为什么百分比和小数是 ERROR】它们只可能来自数据 ——
    没人会在自然语言里凭空写「68.3%」，写出来就是对某条事实的断言。
    绑不上 = 编的，或者读错了值。

    【为什么小整数跳过】1-10 的整数在日常表达里到处都是：
    「前 5 位艺人」「第 3 首」「三条主线」「推荐 5 首」。
    它们绝大多数不是数据断言，而误判成 error 会让 Phase 4 白重写。

    中间那段（11 以上的整数、以及所有带 % 的）判 warning：
    它们更像数据（「你有 128 首」），但也可能是序数或年份的另一种写法，
    打回重写的代价比漏掉一个大。
    """
    if "%" in raw or "." in raw:
        return ERROR
    try:
        value = float(raw)
    except ValueError:
        return WARNING
    if 1 <= value <= 10 and value == int(value):
        return None
    return WARNING


# ============================================================
# L4 实体层
# ============================================================

def check_entities(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """提到的艺人/专辑/流派名，必须能在本轮数据里找到。

    这是「编造了一个不存在的专辑」的**唯一机械防线**。
    名字来自：用户曲目的艺人/专辑/流派 + 本轮所有工具 facts 里的流派名。
    """
    known: list[str] = []

    def index(track) -> None:
        # 【歌名必须进索引】第一版只收了艺人/专辑/流派，结果报告里
        # 「《十年》《浮夸》《稻香》」这类用户自己的歌全被判成「不在数据里」——
        # 一次性误报二十多条。而带书名号的专名恰恰是这一层主要要检查的对象，
        # 漏掉歌名等于把最该认的一类全判错了。
        if track.track_name:
            known.append(track.track_name)
        if track.artist_name:
            known.append(track.artist_name)
        if track.album_name:
            known.append(track.album_name)
        known.extend(track.genres)

    for track in ctx.tracks:
        index(track)

    # facts 里的流派名（genre.album.xxx.tracks 这种 key 里带着流派名）
    for key in ctx.facts:
        parts = key.split(".")
        if len(parts) >= 3 and parts[0] == "genre":
            known.append(parts[-2].replace("_", " "))

    # 【推荐曲目也要进索引】报告解释推荐理由时会提被推荐的那首歌和它的专辑
    # （「这首来自《黑色的梦》」），那不是用户听过的，但确实是数据里真实存在的。
    # 不收录的话每条推荐理由都会被误判。
    rec_ids = [r.get("track_id") for r in (report.get("recommendations") or [])]
    rec_ids = [i for i in rec_ids if i]
    if rec_ids and ctx.connection is not None:
        for track in load_enriched(ctx.connection, rec_ids):
            index(track)

    # 【必须拍平成一个字符串集合，不能留成「集合的列表」】
    # 写成 `[name_variants(n) for n in known]` 再 `for v in known_variants` 的话，
    # v 拿到的是集合而不是字符串，`q in v` 会变成集合成员判断（要求精确相等），
    # 于是「流行歌曲」匹配不上「流行歌曲 (Popular Songs)」——
    # 而这个错【不报错】，只是静默地多出一堆误报。
    # 这个坑在这个仓库里已经出现三次了（音频匹配、这里、还有一次在 Java 侧）。
    known_variants: set[str] = set()
    for name in known:
        known_variants |= name_variants(name)

    # 用「书名号」里包裹的专名当候选。比全文本分词可靠得多，
    # 而且模型提到作品名时几乎总带书名号
    for path, text in walk_texts(report):
        result.checked += 1
        for quoted in re.findall(r"《([^》]+)》", text):
            # 只当警告：书名号里也可能是模型对某个概念的概括说法，
            # 不一定是专名。误判成 error 会让 Phase 4 白重写
            if not any(q in v for v in known_variants for q in name_variants(quoted)):
                result.violations.append(Violation_(
                    "entity", path, f"提到的《{quoted}》不在本轮数据里", WARNING))


# ============================================================
# L5 证据回查层（最强）
# ============================================================

def check_evidence(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """证据/锚点越界、声称的属性查不实、推荐了已有的歌。

    这是五层里最强的一层：它不看模型说了什么，而是**回数据库查它说的对不对**。
    """
    user_ids = set(ctx.evidence.all_ids)
    by_id = {t.track_id: t for t in ctx.tracks}

    # --- 证据必须属于用户 ---
    for path, claim in walk_claims(report):
        for tid in claim.get("evidence_track_ids") or []:
            result.checked += 1
            if tid not in user_ids:
                result.violations.append(Violation_(
                    "evidence", path,
                    f"证据曲目 {tid} 不是用户的歌"
                    + ("（它可能是推荐候选 —— 候选不是用户听过的）"
                       if candidate_ids and tid in candidate_ids else "")))

    # --- 推荐项 ---
    rec_ids = [r.get("track_id") for r in report.get("recommendations") or []]
    candidates = {t.track_id: t for t in load_enriched(ctx.connection, [i for i in rec_ids if i])}

    for i, rec in enumerate(report.get("recommendations") or []):
        path = f"recommendations[{i}]"
        tid = rec.get("track_id")
        result.checked += 1

        if tid in user_ids:
            result.violations.append(Violation_(
                "evidence", path, f"推荐了用户已经有的歌 {tid}"))
        if candidate_ids is not None and tid not in candidate_ids:
            result.violations.append(Violation_(
                "evidence", path, f"推荐 {tid} 不在候选池里"))
        if tid not in candidates:
            result.violations.append(Violation_(
                "evidence", path, f"推荐 {tid} 在库里不存在"))
            continue

        # --- 锚点必须属于用户 ---
        for anchor in (rec.get("relation_to_history") or {}).get("anchors") or []:
            result.checked += 1
            if anchor not in user_ids:
                result.violations.append(Violation_(
                    "evidence", path, f"锚点 {anchor} 不是用户的歌"))

        # --- 声称的属性必须查得实 ---
        # 【这一条是原则 4 的机器可校验形式】
        # 说「同为 mandopop」→ 回查候选的流派里真有 mandopop
        # 说「同属低能量」→ 回查 track_audio_feature，**而且必须是实测行** ——
        #   推断出来的能量不能用来支撑这个断言
        target = candidates[tid]
        dims = set(rec.get("matched_dimensions") or [])

        if "genre" in dims and not target.genres:
            result.violations.append(Violation_(
                "evidence", path, f"声称同流派，但候选 {tid} 没有任何流派标签"))
        if "mood" in dims and target.arousal_measured is None:
            result.violations.append(Violation_(
                "evidence", path,
                f"声称能量相近，但候选 {tid} 没有实测音频特征（推断值不能支撑这个断言）"))
        if "artist" in dims:
            user_artists = {t.artist_id for t in ctx.tracks if t.artist_id}
            if target.artist_id not in user_artists:
                result.violations.append(Violation_(
                    "evidence", path, f"声称同艺人，但候选 {tid} 的艺人不在用户曲库里"))

        # --- 断言「有关系」就必须有锚点 ---
        rel = rec.get("relation_to_history") or {}
        if rel.get("note") and not rel.get("anchors"):
            result.violations.append(Violation_(
                "evidence", path,
                "写了「和用户听过的某首歌有关」但没给锚点 —— 无法核对，等于没解释"))