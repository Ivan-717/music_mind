# M5.2 交接：抓语料落本地

**这一步的 Python 归你写，我验收。** 目标：把艺人条目和流派条目的正文抓到本地，
供 M5.3 做分块和 embedding。

前置：M5.1（`wiki.py`）已完成，实测头部 10 位 **10/10、中英双份**。

---

## 落哪、什么形状

### 一个实体一个文件

```
agent-service/.data/corpus/          ← 和 checkpoints.db 同一层，gitignore 里已有 .data/
    artists/<id>.json
    genres/<id>.json
```

**为什么不是一个大 JSONL**：

| | 一个文件 | 一个实体一个文件 |
|---|---|---|
| 断点续跑 | 要自己记「抓到哪了」 | **文件在就是抓过了** |
| 增量 | 重写整个文件 | 什么都不用做 |
| 单个坏掉 | 全废 | 只废一个 |

这个形状仓库里已经用过两次：封面（`frontend/public/covers/<album_id>.jpg`，
文件在就跳过）和 `backfill_artist_meta.py` 的 `meta_synced_at`。
**「文件在不在」当完成标记**是最省事也最难出错的一种。

### 单个文件的结构

```json
{
  "kind": "artist",
  "id": 173,
  "name": "周杰倫",
  "meta": {
    "country_code": "TW", "type": "Person", "begin_year": 2000,
    "tracks_in_library": 788
  },
  "pages": [
    {"lang": "zh", "title": "周杰倫", "url": "https://zh.wikipedia.org/wiki/周杰倫",
     "chars": 11742, "text": "……"},
    {"lang": "en", "title": "Jay Chou", "url": "https://en.wikipedia.org/wiki/Jay_Chou",
     "chars": 50811, "text": "……"}
  ],
  "fetched_at": "2026-10-05T10:00:00"
}
```

**`meta` 为什么要存**：M5.3 建 Qdrant 时要把这些挂成 payload —— 「只在这个艺人的
条目里检索」「只看中文的」这类过滤全靠它。事后再回数据库捞一遍就又要把两个东西
对齐一次，而那种对齐迟早漂移。

**为什么中英都存**：M5.1 实测英文条目普遍厚 2-4 倍，但中文更贴中文读者。
检索时按语言过滤（或者都检、按语言加权）比现在就砍掉一种灵活。

---

## 你要写的（1 个文件）

### `agent-service/fetch_corpus.py` —— 新增

```python
"""抓语料：艺人条目 + 流派条目，落 .data/corpus/。

用法：
    python fetch_corpus.py                  # 抓缺的（艺人 + 流派）
    python fetch_corpus.py --kind genre     # 只抓流派（129 个，快）
    python fetch_corpus.py --kind artist    # 只抓艺人（696 个，慢）
    python fetch_corpus.py --limit 20       # 先抓 20 个看看
    python fetch_corpus.py --status         # 只看进度，不抓
    python fetch_corpus.py --retry-empty    # 连「抓过但一页都没有」的也重抓

【断点续跑靠文件存不存在】和封面那边同一个规矩：文件在就跳过。
不另写一张进度表 —— 那张表迟早和实际情况对不上，而对不上的表现是
「某些条目永远抓不到」。

【失败不留标记】网络抖动导致抓不到时**不写文件**，下次重跑自然就重试了。
反过来（写一个 failed 标记）是把一次抖动永久记成「已处理」——
`backfill_artist_meta.py` 那边踩过这个坑。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from musicmind_agent.config import PROJECT_ROOT  # noqa: E402
from musicmind_agent.db import get_connection  # noqa: E402
from musicmind_agent.wiki import WikiClient, WikiError, find_pages  # noqa: E402

CORPUS_DIR = PROJECT_ROOT / "agent-service" / ".data" / "corpus"


# ============================================================
# 取实体
# ============================================================

def load_artists(connection) -> list[dict]:
    """库里的艺人 + 几条能当 Qdrant payload 的元数据。

    【为什么要 tracks_in_library】它是「这个人对用户重不重要」的唯一近似。
    检索时可以据此加权 —— 只有一首歌的 session musician 和 788 首的周杰倫
    不该平等对待。
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT a.id, a.name, a.country_code, a.type, a.begin_year,
                   (SELECT COUNT(*) FROM track_artist ta WHERE ta.artist_id = a.id) AS tracks
            FROM artist a
            ORDER BY tracks DESC, a.id
        """)
        return list(cursor.fetchall())


def load_genres(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT g.id, g.name,
                   (SELECT COUNT(*) FROM album_genre ag WHERE ag.genre_id = g.id) AS tracks
            FROM genre g
            ORDER BY tracks DESC, g.id
        """)
        return list(cursor.fetchall())


# ============================================================
# 抓一个
# ============================================================

def target_path(kind: str, entity_id: int) -> Path:
    return CORPUS_DIR / f"{kind}s" / f"{entity_id}.json"


def fetch_one(client: WikiClient, kind: str, row: dict) -> dict | None:
    """抓一个实体的全部语言版本。一页都没有时返回 None（不写文件）。"""
    pages = find_pages(row["name"], client=client)
    if not pages:
        return None

    if kind == "artist":
        meta = {"country_code": row.get("country_code"), "type": row.get("type"),
                "begin_year": row.get("begin_year"),
                "tracks_in_library": row.get("tracks") or 0}
    else:
        meta = {"tracks_in_library": row.get("tracks") or 0}

    return {
        "kind": kind,
        "id": row["id"],
        "name": row["name"],
        "meta": meta,
        "pages": [
            {"lang": p.lang, "title": p.title, "url": p.url,
             # chars 单独存一份：M5.3 分块时要按长度决定要不要切，
             # 每次都 len(text) 也行，但统计和报告里到处都是它
             "chars": len(p.text), "text": p.text}
            for p in pages
        ],
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def save(kind: str, entity_id: int, payload: dict) -> Path:
    path = target_path(kind, entity_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False —— 中文原样存，不然文件里全是 \uXXXX，
    # 出问题时连肉眼都看不了
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ============================================================
# 主流程
# ============================================================

def run(kind: str, limit: int | None, retry_empty: bool, status_only: bool) -> None:
    connection = get_connection()
    try:
        rows = load_artists(connection) if kind == "artist" else load_genres(connection)
    finally:
        connection.close()

    if status_only:
        done = sum(1 for r in rows if target_path(kind, r["id"]).exists())
        print(f"{kind}：{done}/{len(rows)} 已抓")
        return

    if limit is not None:
        rows = rows[:limit]

    client = WikiClient()
    # 【重跑时先拿到已有的清单】每个文件 stat 一次，比在循环里反复 stat 快
    exists = {r["id"]: target_path(kind, r["id"]).exists() for r in rows}

    started = time.time()
    done = skipped = missed = failed = 0
    total_chars = 0

    for i, row in enumerate(rows, start=1):
        if exists[row["id"]]:
            if not retry_empty:
                skipped += 1
                continue
            # --retry-empty：抓过的也看一眼，空的（只有 0 页）就重抓
            old = json.loads(target_path(kind, row["id"]).read_text(encoding="utf-8"))
            if old.get("pages"):
                skipped += 1
                continue

        try:
            payload = fetch_one(client, kind, row)
        except WikiError as e:
            failed += 1
            # 【不打标记】下次重跑自然重试。写个 failed 文件的话，
            # 一次网络抖动就被永久记成「已处理」了
            print(f"[{i}/{len(rows)}] {row['name'][:20]} ✗ {e}")
            continue

        if payload is None:
            missed += 1
            print(f"[{i}/{len(rows)}] {row['name'][:20]} - 维基上没有")
            continue

        save(kind, row["id"], payload)
        done += 1
        chars = sum(p["chars"] for p in payload["pages"])
        total_chars += chars
        print(f"[{i}/{len(rows)}] {row['name'][:20]} "
              f"{'/'.join(p['lang'] for p in payload['pages'])} {chars} 字")

    elapsed = time.time() - started
    print()
    print("=" * 60)
    print(f"{kind}：新抓 {done}  跳过 {skipped}  上游没有 {missed}  失败 {failed}")
    print(f"本次新增 {total_chars / 10000:.1f} 万字，耗时 {elapsed / 60:.1f} 分钟")
    print(f"语料目录：{CORPUS_DIR / (kind + 's')}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="抓维基语料（断点续跑）")
    parser.add_argument("--kind", default="all", choices=["artist", "genre", "all"])
    parser.add_argument("--limit", type=int, default=None, help="只抓前 N 个，先看看")
    parser.add_argument("--retry-empty", action="store_true",
                        help="连「抓过但一页都没有」的也重抓")
    parser.add_argument("--status", action="store_true", help="只看进度")
    args = parser.parse_args()

    kinds = ["genre", "artist"] if args.kind == "all" else [args.kind]
    # 【流派先抓】129 个，几分钟就完，而且是「了解一个流派」那条需求的直接支撑。
    # 艺人 696 个要十几分钟，放后面
    for kind in kinds:
        run(kind, args.limit, args.retry_empty, args.status)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**注意 `PROJECT_ROOT`**：`config.py` 里已经有它（`Path(__file__).resolve().parents[2]`）。
如果没有就加一行，别在这儿另算一遍 —— 两处算路径迟早不一致。

---

## 怎么跑

```bash
cd agent-service

# 先看两个各有多少、已经抓了多少
.venv/Scripts/python.exe fetch_corpus.py --status

# 流派先跑（129 个，几分钟）
.venv/Scripts/python.exe fetch_corpus.py --kind genre

# 再跑艺人（696 个，十几分钟，限速 0.3s/请求）
.venv/Scripts/python.exe fetch_corpus.py --kind artist

# 中断了直接再跑，已抓的会跳过
.venv/Scripts/python.exe fetch_corpus.py --kind artist
```

---

## 验收

```
1. 跑完之后 --status 显示两边的完成数
2. 第二次跑同一个命令 → 应该【全部跳过】，耗时几秒（这是断点续跑的证据）
3. 抽一个文件看：应该是合法 JSON、中英都有、text 不是空的
4. 抓不到的那些【不产生文件】（ls 一下目录里有没有 0 页的文件）
5. 总量对得上：artists/*.json + genres/*.json 的字数合计
```

**期望的数量级**（调研时实测的）：

```
流派   129 个，命中 ~120，中英双份，合计 100 万字量级
艺人   696 个，命中 ~400-500（长尾的 session musician 维基上本来就没有）
       头部平均每人 2-3 万字，合计 1000 万字量级
```

**命中率低于 60% 要停下来看看** —— 那说明 `find_pages` 还有问题，
而不是「维基上就是没有」（头部 10 位实测 100%）。

---

## 坑

1. **别写「抓取失败」的标记文件。** 下次重跑自然重试。写标记 = 把一次网络抖动
   永久记成已处理，而那种错没有任何东西会报警
2. **`ensure_ascii=False`。** 不然文件里全是 `\uXXXX`，出问题时肉眼没法看
3. **`meta` 要一起存。** 它是 M5.3 的 Qdrant payload，事后再回数据库捞一遍
   就等于要求两个东西永远对齐
4. **限速 0.3s 是 `WikiClient` 自己管的**，别在外面再包一层并发 —— 那样限速形同虚设
5. **同名不同人**：按名字查维基时，库里两个不同 MBID 的同名艺人会挑到同一页。
   **当前库实测 0 组同名**（`SELECT name FROM artist GROUP BY name HAVING COUNT(*)>1`
   返回空），所以现在不是问题。
   **但换一批数据（新用户导入别的歌单、按需入库抓进来更多人）之后要重新确认** ——
   一旦出现，`pick_best` 会挑维基自己的排序，可能错误。
   到那时再想「用 MB 的 disambiguation 消歧」也来得及
