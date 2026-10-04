# M3 交接：Agent 主动触发的按需入库

**这一步的 Python 部分是你写，我验收。** 目标：用户问「我想了解 Britpop」，
库里没有 → Agent 去上游找几张代表专辑 → **问用户要不要抓** → 用户点了就抓进来 → 再回答。

对应路线图的 M3。解决的问题是计划 §2 那句：**库只随「用户歌单」增长，
覆盖不了「用户想去发现的」。**

---

## 起点：三件事已经现成

1. **异步入库的整条链已经跑了几百次** —— 排队 / 子进程 / 超时强杀 / 崩溃恢复 /
   入库后重对齐 / 封面。M3 一行都不用改它。
2. **`IngestionWorker` 有个「已解析就复用」的旁路**：`process()` 里——
   `album_name` 非空时，去查「同一歌手 + 同一专辑名」的 DONE 任务，复用它的 release mbid。
   **注意：这不是「album_name 就是 mbid」**（我一开始读反了，见下面的坑）。
   所以「已经知道要抓哪张」这件事，要另加一条路径（用 `job.release_mbid`）。
3. **MusicBrainz 查询能力两边都有**：Java 侧 `MusicBrainzLookupService`，
   data-pipeline 侧 `MusicBrainzClient.search_artist` / `get_artist_releases`。
   （agent-service 里没有，那是这一步要加的。）

---

## 三个已经定下来的设计

### ① 必须问用户，不能自动抓

```
用户：我想了解 Britpop
   ↓  Agent 调 search_upstream，拿到 5 张候选
   ↓
Agent：这几张不在你库里。要抓进来吗？（约 2 分钟）
       · (What's the Story) Morning Glory? — Oasis, 1995
       · Parklife — Blur, 1994
   ↓  用户点「抓进库里」
```

三条理由，缺一不可：
- **1 req/s**，抓 5 张专辑要 30-60 秒 —— 用户得知道自己在等什么
- **让 LLM 自主决定抓什么是会抓飞的**。配额 + 确认是必须的
- 「原则 2：技术必须有实际用途」——**不预先铺数据**

### ② 抓进来的歌落在一张叫「AI 帮你找的」歌单里

**这是这一步最要紧的取舍，先说清楚。**

Agent 抓的专辑不属于任何用户歌单，所以 `ingestion_job.track_row_id`（NOT NULL，
外键指向 `user_playlist_track`）没有值可填。三条出路：

| | 做法 | 代价 |
|---|---|---|
| a | 给 `ingestion_job` 加一张新表 + 新 worker | 两个队列、两个 worker，都受 1 req/s 限速，要串行 —— 复杂度翻倍 |
| b | 把 `track_row_id` 放开为可空 | 所有按歌单行显示任务的地方都要处理 null（`IngestionJobMapper` 一片） |
| **c** | **建一张 `provider='agent'` 的 import，把候选写成它的行** | **零 schema 改动** |

**选 c**，因为它顺手多出三件事：

- 抓进来的歌**用户可以浏览、试听、一键全部加入收藏** —— 现成的功能
- **可追溯**：用户看得见「我让 AI 找过什么」，不是凭空多出来一堆
- 入库后的**重对齐天然可用**（`artist_name` / `title` 就在行里，Java 不用另找出处）

代价是「我的歌单」页会多一张。**这是有意的**，不是副作用。

### ③ Python 只查上游，不写任何队列

```
Python（chat.py 里的工具）  只做「查 MB → 返回候选」
Java（/api/agent/fetch）    写歌单行 + 排 ingestion_job
```

Python 直连写 `ingestion_job` 会破坏归属规则（队列归 Java 写），
而且「排队」这个动作本来就有归属校验要做（这歌是不是用户能要的）。

---

## 你要写的（3 个文件）

### 1. `musicmind_agent/upstream.py` —— 新增

```python
"""MusicBrainz 查询。**只读上游，不写任何本地表、不排队。**

【和 data-pipeline 那个 client 的关系】那个在另一个 venv 里，import 不过来，
而且它是给批量导入用的（有增量同步、entity 解析那一堆）。
这里只要一件事：**按几个条件搜 release，返回够组一张歌单的候选**。

【限速 1 请求/秒是硬要求】MusicBrainz 对匿名调用是 1 req/s，
超了会被封（他们的 User-Agent 政策要求带上联系方式）。
这个类自己 sleep，不指望调用方守规矩 —— 和 CoverArtClient 同一个形状。

【为什么是结构化参数，不是让模型写查询串】MB 的查询是 Lucene 语法
（`release:xxx AND artist:yyy`），让模型自由发挥等于让它拼一个可能语法错的串，
而错误信息是 400，看起来像我们的 bug。参数在这里拼，模型只填值。
"""

from __future__ import annotations

import time

import requests

# 【User-Agent 从 config 拿，别在这儿写一个】
# .env 里的 MUSICBRAINZ_USER_AGENT 是**三边共用**的：Java 的 application.yaml、
# data-pipeline 的 config/settings.py、还有这里。
# 而且**绝对不能编一个假 URL 当兜底** —— MusicBrainz 的 UA 政策要求带真实联系方式，
# 他们据此联系你。编一个不存在的地址比留空更糟，2026 年会因此被限流甚至封
from musicmind_agent.config import MUSICBRAINZ_API, MUSICBRAINZ_USER_AGENT

MB_BASE = MUSICBRAINZ_API
USER_AGENT = MUSICBRAINZ_USER_AGENT
MIN_INTERVAL = 1.0


class UpstreamError(Exception):
    pass


class MusicBrainzSearch:
    def __init__(self, timeout: int = 20, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        # trust_env 默认 True，会读 .env 里的 HTTPS_PROXY（config 那边 load_dotenv 过了）
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last = 0.0

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(self.max_retries + 1):
            self._wait()
            try:
                resp = self.session.get(f"{MB_BASE}{path}", params=params,
                                        timeout=self.timeout)
                self._last = time.monotonic()
            except Exception as e:
                if attempt == self.max_retries:
                    raise UpstreamError(f"{type(e).__name__}: {e}") from e
                time.sleep(2 * (attempt + 1))
                continue

            if resp.status_code == 503:
                # MB 忙的时候会 503，等一会儿重试是官方建议
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise UpstreamError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        raise UpstreamError("重试完了还是失败")

    def search_releases(self, *, artist: str | None = None,
                        release: str | None = None,
                        tag: str | None = None,
                        year_from: int | None = None,
                        year_to: int | None = None,
                        limit: int = 8) -> list[dict]:
        """按条件搜 release。返回够给用户挑的一小把。

        **至少要给一个条件** —— 无条件搜索等于「随便给我几张专辑」，
        那对用户没有意义，而且会白白吃掉限速配额。
        """
        parts = []
        if release:
            parts.append(f'release:"{release}"')
        if artist:
            parts.append(f'artist:"{artist}"')
        if tag:
            # tag 在 MB 上是社区打的，覆盖不均 —— 常见的流派基本都有，
            # 冷门的长尾可能空手而归。空了就如实说找不到
            parts.append(f'tag:"{tag}"')
        if year_from or year_to:
            lo = year_from or 1900
            hi = year_to or 2030
            parts.append(f"date:[{lo} TO {hi}]")

        if not parts:
            raise UpstreamError("至少要给一个搜索条件")

        data = self._get("/release", {
            "query": " AND ".join(parts),
            "fmt": "json",
            "limit": max(1, min(limit, 25)),
        })

        out = []
        for r in data.get("releases", []):
            credits = r.get("artist-credit") or []
            name = "".join(
                (c.get("name") or "") + (c.get("joinphrase") or "") for c in credits
            ).strip()
            date = r.get("date") or ""
            out.append({
                "release_mbid": r.get("id"),
                "title": r.get("title"),
                "artist": name or "未知",
                "year": date[:4] if date[:4].isdigit() else None,
                "primary_type": r.get("release-group", {}).get("primary-type"),
                "track_count": r.get("track-count"),
            })
        return out
```

**这一段你只要抄。** 有几个地方是踩过坑才那么写的，别改：
- `_wait()` 自己限速，不靠调用方
- 503 是 MB 忙，重试是官方建议
- 参数在代码里拼，模型只填值

### 2. 注册一个 Tier-1 工具

放 `tools/explore.py` 末尾（它已经是 Tier-1 探针的家）：

```python
# ============================================================
# 查上游（本地库里没有的东西）
# ============================================================

@register(
    "search_upstream", 1,
    "去 MusicBrainz 找本地库里没有的专辑。"
    "**只返回候选，不抓取** —— 抓取要用户点了才会发生",
    {
        "artist": "艺人名",
        "release": "专辑名",
        "tag": "风格标签，比如 britpop / j-rock",
        "year_from": "最早年份",
        "year_to": "最晚年份",
    },
)
def search_upstream(ctx: ToolContext, args: dict) -> ToolResult:
    from musicmind_agent.upstream import MusicBrainzSearch, UpstreamError

    # 至少要给一个条件 —— 空条件等于「随便给我几张」，对用户没意义
    if not any(args.get(k) for k in ("artist", "release", "tag", "year_from", "year_to")):
        return ToolResult(tool="search_upstream",
                          warnings=["至少要给一个搜索条件（artist / release / tag / 年份）"])

    try:
        found = MusicBrainzSearch().search_releases(
            artist=args.get("artist"),
            release=args.get("release"),
            tag=args.get("tag"),
            year_from=args.get("year_from"),
            year_to=args.get("year_to"),
            limit=int(args.get("limit", 8)),
        )
    except UpstreamError as e:
        # 上游挂了要说出来。返回空 rows 而不带 warning 的话，
        # 模型会以为「MusicBrainz 上没有」—— 和「网络断了」是两回事
        return ToolResult(tool="search_upstream",
                          warnings=[f"查上游失败：{e}"])

    # 【排掉库里已经有的】按 MBID 比 —— 专辑表里 100% 有 musicbrainz_id
    with ctx.connection.cursor() as cursor:
        cursor.execute("SELECT musicbrainz_id FROM music_release")
        known = {row["musicbrainz_id"] for row in cursor.fetchall()}
    fresh = [x for x in found if x["release_mbid"] not in known]

    return ToolResult(
        tool="search_upstream",
        facts={"upstream.found": len(found), "upstream.not_in_library": len(fresh)},
        rows=fresh,
        evidence=[],          # 上游的东西不是「用户听过的」，一条证据都不能给
        coverage=cov(len(found), len(fresh), "「本地没有」的才列出来"),
        warnings=([] if fresh else ["上游找到的本地都有了，没有需要抓的"]),
    )
```

### 3. `chat.py` 加 `fetch_proposals`

**三处改动**，都是增量的：

**a. `CHAT_SYSTEM` 的「直接回答」那行，多一个字段：**

```python
直接回答：
{"answer": "...", "recommendations": [...], "fetch_proposals": [...]}

**fetch_proposals 只在「用户问的东西库里没有、而 search_upstream 找到了」时填。**
每条是 {"release_mbid": "从工具结果里照抄", "why": "为什么建议抓这张"}，最多 5 条。
```
并在硬规则里补一句：
```
   · 库里没有的，可以用 search_upstream 去找候选，然后**问用户要不要抓** ——
     但你自己不能抓，也不能假设已经抓了。抓取要用户点。
```

**b. `_resolve_recos` 旁边加一个解析函数：**

```python
def _resolve_proposals(items, upstream_rows) -> list[dict]:
    """把模型提议的 release 映射回 search_upstream 真返回的那几条。

    **和推荐一样：只认工具真的返回过的 mbid。** 模型凭印象写一个 mbid 的话，
    抓的时候会去抓一张它想象中的专辑 —— 而 MB 上那个 id 可能根本不存在，
    或者存在但不是它说的那张。越界的直接丢，不猜。
    """
    by_mbid = {r["release_mbid"]: r for r in upstream_rows}
    out = []
    for item in (items or [])[:5]:
        row = by_mbid.get(item.get("release_mbid"))
        if row is None:
            continue
        out.append({**row, "why": item.get("why") or ""})
    return out
```

**c. `chat()` 里攒 upstream 的行：**

工具循环里 `search_upstream` 的 rows 要单独留一份（它们没有 track_id，
`_number_rows` 不会碰它们）：

```python
        upstream_rows: list[dict] = []
        ...
            # 在工具循环里，拿到结果之后
            if name == "search_upstream":
                upstream_rows.extend(result.rows)
        ...
        # 返回时
        return {
            "answer": render_text(text, ctx.facts, strict=False),
            "recommendations": _resolve_recos(raw.get("recommendations"), pool, ctx),
            "fetch_proposals": _resolve_proposals(raw.get("fetch_proposals"), upstream_rows),
            "used_tools": used,
        }
```

---

## 我接的（Java + 前端，你不用管）

- `POST /api/agent/fetch {proposals: [{release_mbid, title, artist, year}]}`
  → 建/复用一张 `provider='agent'` 的 import，写 `user_playlist_track` 行，
    直接排 `ingestion_job`（`album_name` = release_mbid，worker 会跳过搜索）
  → 返回 `{queued, importId}`，前端提示「已排进队列，约 N 分钟」
- 前端：把 `fetch_proposals` 渲染成卡片 + 「抓进库里」按钮
- 一次最多 5 张（和 `MAX_BATCH` 对齐），越界 400

---

## 验收

```
1. 问「我想了解 Britpop」（库里 0 张）
   → 回答里说明库里没有，并给出 fetch_proposals
2. proposals 里的 release_mbid 都是 search_upstream 真返回过的
   （模型自己编一个 → 应该被丢掉，列表为空）
3. 点「抓进库里」→ 队列开始跑 → 「我的歌单」页出现一张「AI 帮你找的」
4. 抓完之后再问同一个问题 → 这次基于库里的数据回答，不再提议抓
5. 一次最多 5 张，超过 → 400
6. 越权：B 看不到 A 的「AI 帮你找的」歌单
7. 上游挂了（断网）→ 回答里说明「查上游失败」，**不是**「MusicBrainz 上没有」
```

第 7 条是这一批里最容易漏的：`search_upstream` 返回空 rows 时，
**必须带 warning**，否则模型会把「网络断了」说成「上游没有这个东西」。

---

## 坑

1. **MB 限速 1 req/s**。`MusicBrainzSearch` 自己 sleep，别在外面再包一层并发
2. **`tag:` 的覆盖不均**。常见的流派基本都有，长尾可能空手。
   空了要如实说「没找到」，不能说「这个风格不存在」
3. **`release_mbid` 不能由模型写**。它见过一堆 uuid，会照着格式编一个 ——
   和推荐那边「只认候选池里的序号」是同一条规矩
4. **不要自动抓**。哪怕模型很想给用户一个满意的答案
5. **抓完不要立刻在同一轮回答**。入库是异步的（30-60 秒），
   这一轮已经结束了。让用户再问一次 —— 或者我这边在前端加个「抓好了，再问一次」的提示

---

## 实际踩到的两个（2026-10-04，都在 Java 侧）

### 「已经知道要抓哪张」不能用 `album_name` 表达

我一开始读错了 `IngestionWorker.process()` 那段三元，以为
**「`album_name` 非空 = 它就是 release mbid」**。实际语义是
「同一歌手 + 同一专辑名，复用别的 job 解析过的 mbid」，兜底还是要走
`lookupService.findRelease(...)` —— **那是录音搜索**。

于是 Agent 抓的专辑被拿去搜录音，而给的名字是**专辑名**，必然找不到。
5 张里 3 张 `NOT_FOUND`，错误信息还写着「MusicBrainz 上没有可入库的专辑」，
指不到真正的原因。

**正解**：用 `job.release_mbid` 这个字段本身（排队时就填好 = 「就是这张」），
worker 在解析逻辑最前面加一条「已填就直接用」。

### `INSERT INTO ingestion_job` 里没有 `release_mbid`

补了上一处之后还是失败。查库发现新任务的 `release_mbid` 全是 `None`。

原因：**`release_mbid` 本来是 worker 解析完之后写的「输出」列**，
所以最初的 INSERT 语句里根本没有它 —— `job.setReleaseMbid(...)` 的值
被**静默丢掉**，不报错。

这类「set 了但 INSERT 没列这一列」的错在所有语言里都不报错，
只能靠「查一下库里到底写进去没有」发现。
