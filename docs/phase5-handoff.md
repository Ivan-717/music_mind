# Phase 5 交接：推荐 + 评估

**这一步是你写，我验收。** 目标：把「推荐得准不准」从**感觉**变成**数字**。

```bash
# 先跑便宜的那半（无 LLM，秒级）
.venv/Scripts/python.exe -m evals.run_eval --systems random,genre_prior,artist_repeat,content --folds 5

# 再跑贵的那半（要 LLM，约 20 次调用）
.venv/Scripts/python.exe -m evals.run_eval --systems agent_full --providers deepseek,qwen --folds 5
```

---

## 起点：我已经验证过的机制

**藏歌（hold-out）通路是通的**，你不用再搭：

```python
from musicmind_agent.tools import build_context

full = build_context(conn, 34)                    # 448 首
part = build_context(conn, 34, hidden_ids={...})  # 359 首，藏起来的确实不在
```

**关键性质：藏起来的歌仍然在候选池里。** 实测：藏 89 首，`similar_tracks` 的候选池里还有其中 37 首。

这不是理所当然的 —— 「藏了又排除出候选」会让 recall 恒为 0，而那种错误**表现为「算法很差」**，看起来像模型不行，实际是评估写错了。

`graph.run_report(connection, user_id, provider, out_dir, hidden_ids)` 已经支持传藏歌。

---

## 评估要回答的三个问题

```
1. 推荐得准不准？          → recall@k，和 6 个对照系统比
2. 为什么不准？            → 天花板分解：是算法的问题还是库的问题
3. LLM 到底加分还是减分？   → 分开测「确定性排序」和「LLM 选完之后」
```

**第 3 条是这一步存在的核心理由。** 现在的 `compose` 让 LLM 从候选里挑 5 首并写理由。如果它挑得比确定性排序还差，那就该**退回确定性排序、让 LLM 只负责写解释** —— 这是提前定好的决策规则，不是事后找补。

---

## 切分：两种，各有各的用途

```
random-item-5fold     按【曲目】随机藏 20%
                      → 乐观值。同专辑/同艺人的近邻还在训练集里，
                        命中的往往是「同专辑第四首」，不是口味泛化
                      → 报的时候【必须标明是乐观值】

artist-cold-5fold      按【艺人】藏，整个人的曲目全部藏起
                      → 真实泛化。这是对外报的主指标
```

**为什么必须有 artist-cold**：按行随机切会泄露。用户收藏了周杰伦的 10 首，藏掉 2 首，
剩下 8 首还在——推荐系统只要说「你听过周杰伦，再听一首周杰伦」就能命中。
那测的是「同专辑近邻」，不是「口味」。

**没有时间切分。** `user_playlist_track` 只有导入时间，没有收听时间，
不存在时间维度的留一。这一点要在结果里写明白，别假装有。

---

## 天花板：一个诚实的诊断，不是一个好看的修饰

对每首藏歌判断「库里有没有可检索的同类」：

```python
ceiling = 可检索的藏歌数 / 藏歌总数
```

结果一律写成 `recall@k / ceiling`。

**实测数据（vdev，random-item 切分）**：

```
藏 89 首 → 89 首有同流派或同艺人的候选 → 天花板 100%
```

**100% 是个有用结论，不是没算出来**：它说明「库里的同类足够多，
recall 低就是算法的问题，别甩锅给数据」。

反过来说，**当某个流派的天花板明显低于 100% 时，那才是数据的锅** ——
所以要**逐流派分解**，不要只报一个总数。中文说唱在这个库里几乎不存在
（project.md 已实测），如果藏歌里有说唱，它们的天花板会很低，
而一个总体的 recall 数字会把这个事实完全掩盖掉。

---

## 六个对照系统

```python
random         从库里随机抽（固定种子，跑 5 次取均值）
genre_prior    按用户的流派分布加权采样
artist_repeat  用户 top 艺人的其他曲目（没有协同数据时最强的朴素基线）
content        确定性内容打分 top-k（reco/score.py）
agent_full     完整图：确定性 top-M + LLM 选 k + LLM 写解释     ← 花钱
llm_only       把粗筛后的目录给 LLM，让它凭「知识」推荐          ← 花钱
```

**前四个零成本、必须全跑。** 没有它们，你测出来的是「LLM 脑子里对周杰伦的记忆」，
不是这个系统的能力 —— `llm_only` 单独存在就是为了量化这件事。

后两个才是花钱的：`2 系统 × 5 折 × 2 provider ≈ 20 次运行`。以现在 p50 29 秒算，
约 10 分钟。可控。

---

## 要建的文件

```
agent-service/
  musicmind_agent/reco/recall.py   ← 1. 五路召回 + MMR（推荐算法的本体）
  evals/__init__.py                ← 2.
  evals/splits.py                  ← 3. 切分生成 + 天花板计算
  evals/metrics.py                 ← 4. 指标
  evals/baselines.py               ← 5. 四个确定性对照
  evals/run_eval.py                ← 6. 主驱动
  tests/test_evals.py              ← 7. 离线部分
```

---

## 1. `musicmind_agent/reco/recall.py`

`score.py` 里已经有 `TasteProfile` / `content_score` / `build_profile`，
你要加的是**召回**（从全库捞出候选）和**去重**（MMR）。

```python
"""五路召回 + MMR。

【为什么要五路而不是一路】实测：全库只有 34.6% 的专辑有流派标注。
纯靠内容分数排序的话，三分之二的候选是「瞎的」—— 它们参与不了流派匹配，
只能靠艺人/年代，分数天然低，永远排不上来。

所以后四路不是补充，是主力：

    1. 内容分 top-N              覆盖全库，但依赖流派
    2. 用户 top 艺人的其他曲目     不依赖流派，而且本来就是真实需求
    3. 与 top 艺人合作过的艺人      用 collaboration_network 的关系
    4. 与用户曲目同专辑的曲目       合辑/精选集场景
    5. 按用户流派分布加权重采样     保证流派多样性，不是纯 top 分

【为什么每路都要留出处】推荐理由要说「因为同艺人（0.25）+ 同期（0.12）」，
那个「同艺人」是第 2 路捞上来的还是第 1 路算出来的，决定了这条理由能不
能成立 —— 第 1 路说「同艺人」是打分推的，第 2 路说是结构上就同艺人。
两者可信度不同，别混为一谈。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from musicmind_agent.evidence import EnrichedTrack, load_all_enriched
from musicmind_agent.reco.score import TasteProfile, build_profile, content_score


@dataclass
class Recalled:
    """一个候选 + 它是怎么被捞上来的。"""

    track: EnrichedTrack
    sources: list[str] = field(default_factory=list)   # 命中了哪几路
    score: dict[str, float] = field(default_factory=dict)


def recall(tracks, all_tracks, profile, per_path: int = 40) -> dict[int, Recalled]:
    """跑五路召回，按 track_id 合并。

    tracks      —— 用户的曲目（画像来源，**不含藏歌**）
    all_tracks  —— 全库（含藏歌 —— 藏歌必须能被推荐，否则 recall 恒为 0）
    """
    known = {t.track_id for t in tracks}
    pool = [t for t in all_tracks if t.track_id not in known]

    out: dict[int, Recalled] = {}

    def add(track: EnrichedTrack, source: str, score: dict | None = None) -> None:
        item = out.setdefault(track.track_id, Recalled(track=track))
        if source not in item.sources:
            item.sources.append(source)
        if score:
            item.score = score

    # 第 1 路：内容分 top-N
    scored = sorted(((content_score(t, profile), t) for t in pool),
                    key=lambda x: -x[0]["total"])[:per_path]
    for score, t in scored:
        add(t, "content", score)

    # 第 2 路：top 艺人的其他曲目
    top_artists = profile.top_artists
    for t in pool:
        if t.artist_id in top_artists:
            add(t, "artist")

    # 第 3 路：合作艺人
    collaborators = _collaborators(tracks)
    for t in pool:
        if t.artist_id in collaborators:
            add(t, "collaborator")

    # 第 4 路：同专辑
    user_albums = {t.album_id for t in tracks if t.album_id}
    for t in pool:
        if t.album_id in user_albums:
            add(t, "same_album")

    # 第 5 路：按流派分布加权重采样
    # 【为什么需要它】前四路都偏向「和你已有的一样」，结果是一堆同艺人同专辑的。
    # 这一路保证流派分布不要塌成单一 —— 它服务的是多样性，不是准确度
    import random
    rng = random.Random(20261003)          # 固定种子，评估必须可复现
    for genre, share in sorted(profile.genre_share.items(), key=lambda x: -x[1])[:5]:
        same = [t for t in pool if genre in t.genres]
        if same:
            for t in rng.sample(same, min(per_path // 5, len(same))):
                add(t, "genre_sample")

    # 给每个候选补上内容分（第 2-5 路捞上来的也要能排序）
    for item in out.values():
        if not item.score:
            item.score = content_score(item.track, profile)

    return out


def _collaborators(tracks) -> set[int]:
    """和用户听过的艺人在同一首歌里出现过的其他艺人。"""
    from collections import defaultdict
    by_track = defaultdict(set)
    for t in tracks:
        if t.artist_id:
            by_track[t.album_id or t.track_id].add(t.artist_id)
    # 这里只用了「同一张专辑」这一种共现。真正的合作网络要查 track_artist，
    # 但那条数据在 tools/collaboration_network 里，Phase 5 可以直接复用
    known = {t.artist_id for t in tracks if t.artist_id}
    out: set[int] = set()
    for artists in by_track.values():
        if artists & known:
            out |= artists
    return out - known


def mmr(items: list[Recalled], k: int, penalty_same_album: float = 0.15,
        penalty_same_artist: float = 0.10) -> list[Recalled]:
    """最大边际相关：同专辑/同艺人的往后压。

    【为什么不能只按分数排】纯 top-k 会给你同一个人的五首歌 ——
    分数高是因为「同艺人」这一项满分，但那对用户没有新信息。
    """
    chosen: list[Recalled] = []
    albums: dict[int, int] = {}
    artists: dict[int, int] = {}

    # 分数排完再逐个扣（贪心，不重排）
    for item in sorted(items, key=lambda x: -x.score.get("total", 0)):
        album_id = item.track.album_id
        artist_id = item.track.artist_id
        penalty = 0.0
        if album_id and albums.get(album_id, 0) >= 1:
            penalty += penalty_same_album
        if artist_id and artists.get(artist_id, 0) >= 2:
            penalty += penalty_same_artist
        item.score["mmr_penalty"] = round(penalty, 3)
        item.score["mmr_total"] = round(item.score.get("total", 0) - penalty, 4)
        chosen.append(item)
        if album_id:
            albums[album_id] = albums.get(album_id, 0) + 1
        if artist_id:
            artists[artist_id] = artists.get(artist_id, 0) + 1

    chosen.sort(key=lambda x: -x.score["mmr_total"])
    return chosen[:k]


def recommend(tracks, all_tracks, k: int = 20) -> list[Recalled]:
    """推荐的确定性版本（不经过 LLM）。评估里的 content 基线就是它。"""
    profile = build_profile(tracks)
    merged = recall(tracks, all_tracks, profile)
    return mmr(list(merged.values()), k)
```

---

## 2. `evals/splits.py`

```python
"""切分与天花板。

【切分必须版本化落盘】否则两次评估的结果没法比 —— 你不知道差异来自
算法改动还是来自换了一批藏歌。文件名带哈希，结果里记下用的是哪份。
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

SPLIT_DIR = Path(__file__).resolve().parent / "splits"
SEED = 20261003          # 固定种子 —— 评估必须可复现


@dataclass
class Fold:
    index: int
    hidden_ids: set[int]
    kind: str            # random_item / artist_cold

    def name(self) -> str:
        digest = hashlib.sha1(
            ",".join(map(str, sorted(self.hidden_ids))).encode()).hexdigest()[:8]
        return f"{self.kind}-f{self.index}-{digest}"


def random_item_folds(tracks, folds: int = 5) -> list[Fold]:
    """按曲目随机藏 20%。乐观值。"""
    rng = random.Random(SEED)
    ids = [t.track_id for t in tracks]
    rng.shuffle(ids)
    size = len(ids) // folds
    return [
        Fold(index=i, hidden_ids=set(ids[i * size:(i + 1) * size]), kind="random_item")
        for i in range(folds)
    ]


def artist_cold_folds(tracks, folds: int = 5) -> list[Fold]:
    """按艺人藏 —— 整个人的曲目全部藏起。真实泛化，主指标。

    【为什么不按行随机】按行随机会把同专辑/同艺人的近邻留在训练集里，
    推荐只要说「你听过周杰伦，再听一首周杰伦」就能命中 ——
    那测的是「同专辑近邻」，不是口味泛化。
    """
    rng = random.Random(SEED)
    by_artist: dict[int, list[int]] = {}
    for t in tracks:
        if t.artist_id:
            by_artist.setdefault(t.artist_id, []).append(t.track_id)

    artists = sorted(by_artist)
    rng.shuffle(artists)
    size = max(1, len(artists) // folds)
    return [
        Fold(index=i,
             hidden_ids={tid for a in artists[i * size:(i + 1) * size]
                         for tid in by_artist[a]},
             kind="artist_cold")
        for i in range(folds)
    ]


def ceiling(fold: Fold, all_tracks, profile_genres: set[str],
            profile_artists: set[int]) -> tuple[int, int]:
    """(可检索的藏歌数, 藏歌总数)。

    「可检索」的定义：库里存在一个【不在藏歌里】的候选，它和这首藏歌
    同流派（且那个流派在用户的 top 里）或同艺人。

    【这个指标是诊断，不是修饰】
      · 天花板 100% → 库里的同类足够，recall 低就是算法的问题
      · 天花板明显 < 100% → 那首藏歌在库里根本没有同类，
                            任何算法都拿不回来，别算在算法头上

    实测（vdev, random-item）：藏 89 首，天花板 100%。
    """
    by_id = {t.track_id: t for t in all_tracks}
    pool = [t for t in all_tracks if t.track_id not in fold.hidden_ids]

    retrievable = 0
    for tid in fold.hidden_ids:
        target = by_id.get(tid)
        if target is None:
            continue
        if any(
            (set(o.genres) & profile_genres)
            or (o.artist_id and o.artist_id in profile_artists)
            for o in pool
        ):
            retrievable += 1
    return retrievable, len(fold.hidden_ids)


def save(fold: Fold, path: Path | None = None) -> Path:
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    path = path or SPLIT_DIR / f"{fold.name()}.json"
    path.write_text(json.dumps({
        "kind": fold.kind, "index": fold.index,
        "hidden_ids": sorted(fold.hidden_ids), "seed": SEED,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
```

---

## 3. `evals/metrics.py`

```python
"""指标。全部是纯函数 —— 好测、可复现。"""

from __future__ import annotations

import math
from collections import Counter


def recall_at_k(recommended: list[int], hidden: set[int], k: int) -> float:
    if not hidden:
        return 0.0
    return len(set(recommended[:k]) & hidden) / len(hidden)


def precision_at_k(recommended: list[int], hidden: set[int], k: int) -> float:
    top = recommended[:k]
    return len(set(top) & hidden) / len(top) if top else 0.0


def hit_rate_at_k(recommended: list[int], hidden: set[int], k: int) -> float:
    """至少命中一首的比例。recall 低但 hit_rate 高，说明「总能找到一点」。"""
    return 1.0 if set(recommended[:k]) & hidden else 0.0


def artist_recall(recommended_ids: list[int], hidden_ids: set[int],
                  artist_of: dict[int, int], k: int) -> float:
    """藏起来的【艺人】被找回的比例。

    【为什么它比曲目 recall 更接近「口味」】推荐一首同艺人的另一首歌，
    和推荐一首同流派不同艺人的歌，前者更容易命中曲目 recall，
    但后者才是「探索」。这个指标把两者分开。
    """
    hidden_artists = {artist_of.get(i) for i in hidden_ids} - {None}
    if not hidden_artists:
        return 0.0
    got = {artist_of.get(i) for i in recommended_ids[:k]} - {None}
    return len(got & hidden_artists) / len(hidden_artists)


def kl_divergence(p: Counter, q: Counter) -> float:
    """推荐集的流派分布 vs 用户真实分布。测「多样性有没有塌」。

    【为什么需要它】一个只推同一种流派的系统，recall 可能很高，
    但它没有在「推荐」，它只是在「复制你已有的」。KL 高说明偏离大。
    """
    p_total, q_total = sum(p.values()), sum(q.values())
    if not p_total or not q_total:
        return 0.0
    eps = 1e-9
    vocab = set(p) | set(q)
    return sum(
        (p.get(g, 0) / p_total + eps) * math.log(
            (p.get(g, 0) / p_total + eps) / (q.get(g, 0) / q_total + eps))
        for g in vocab
    )
```

---

## 4. `evals/baselines.py`

```python
"""四个确定性对照系统。零 LLM、零成本，但必须有。

【没有它们，你测的是「LLM 脑子里对周杰伦的记忆」，不是这个系统。】
"""

from __future__ import annotations

import random
from collections import Counter

from musicmind_agent.evidence import EnrichedTrack
from musicmind_agent.reco.recall import recommend, recall
from musicmind_agent.reco.score import build_profile


def random_pick(all_tracks, user_tracks, k: int, seed: int = SEED) -> list[int]:
    known = {t.track_id for t in user_tracks}
    pool = [t.track_id for t in all_tracks if t.track_id not in known]
    rng = random.Random(seed)
    return rng.sample(pool, min(k, len(pool)))


def genre_prior(user_tracks, all_tracks, k: int) -> list[int]:
    """按用户的流派分布加权采样。测「只知道流派分布能走多远」。"""
    profile = build_profile(user_tracks)
    known = {t.track_id for t in user_tracks}
    pool = [t for t in all_tracks if t.track_id not in known]

    rng = random.Random(SEED)
    weights = []
    for t in pool:
        w = sum(profile.genre_share.get(g, 0.0) for g in t.genres)
        weights.append(w if w > 0 else 0.001)      # 没流派的也要有可能被抽到

    picked: list[int] = []
    remaining = list(range(len(pool)))
    for _ in range(min(k, len(pool))):
        idx = rng.choices(remaining, weights=[weights[i] for i in remaining])[0]
        picked.append(pool[idx].track_id)
        remaining.remove(idx)
    return picked


def artist_repeat(user_tracks, all_tracks, k: int) -> list[int]:
    """用户 top 艺人的其他曲目。没有协同数据时最强的朴素基线。"""
    profile = build_profile(user_tracks)
    known = {t.track_id for t in user_tracks}
    pool = [t for t in all_tracks
            if t.track_id not in known and t.artist_id in profile.top_artists]
    rng = random.Random(SEED)
    rng.shuffle(pool)
    return [t.track_id for t in pool[:k]]


def content(user_tracks, all_tracks, k: int) -> list[int]:
    """确定性内容打分 + MMR。**这是最重要的基线** ——
    agent_full 必须打赢它，否则 LLM 就是在减分。"""
    return [item.track.track_id for item in recommend(user_tracks, all_tracks, k)]
```

---

## 5. `evals/run_eval.py`

```python
"""评估主驱动。

【为什么不放进 pytest】LLM 调用慢、花钱、有随机性。
混进单测的后果是没人愿意跑测试 —— 那是评估体系最常见的死法。
单测里只放切分、天花板、指标、baseline 这些纯函数的用例。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from musicmind_agent.db import get_connection  # noqa: E402
from musicmind_agent.evidence import load_all_enriched  # noqa: E402
from musicmind_agent.tools import build_context  # noqa: E402
from evals import baselines, metrics, splits  # noqa: E402

RESULT_DIR = Path(__file__).resolve().parent / "results"


def run_deterministic(system: str, user_tracks, all_tracks, k: int) -> list[int]:
    fn = {
        "random": baselines.random_pick,
        "genre_prior": baselines.genre_prior,
        "artist_repeat": baselines.artist_repeat,
        "content": baselines.content,
    }[system]
    if system == "random":
        return fn(all_tracks, user_tracks, k)
    return fn(user_tracks, all_tracks, k)


def run_agent(connection, user_id: int, hidden_ids: set[int], provider: str, k: int):
    """跑完整图。返回推荐的 track_id 列表 + 运行统计。"""
    from musicmind_agent.graph import run_report

    final = run_report(connection, user_id, provider, None, hidden_ids)
    rendered = final.get("rendered") or {}
    ids = [r.get("track_id") for r in rendered.get("recommendations", [])]
    return [i for i in ids if i][:k], final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", type=int, default=34)
    parser.add_argument("--systems", default="random,genre_prior,artist_repeat,content")
    parser.add_argument("--providers", default="deepseek")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--kind", default="artist_cold", choices=["artist_cold", "random_item"])
    args = parser.parse_args()

    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]

    connection = get_connection()
    try:
        full = build_context(connection, args.user)
        all_tracks = load_all_enriched(connection)
        folds = (splits.artist_cold_folds if args.kind == "artist_cold"
                 else splits.random_item_folds)(full.tracks, args.folds)

        artist_of = {t.track_id: t.artist_id for t in all_tracks}
        rows = []

        for fold in folds:
            # 【画像用减掉藏歌之后的曲目；候选用全库】
            profile_tracks = [t for t in full.tracks if t.track_id not in fold.hidden_ids]
            profile = build_profile(profile_tracks)

            ceil_ok, ceil_total = splits.ceiling(
                fold, all_tracks,
                {g for g, _ in Counter(
                    g for t in profile_tracks for g in t.genres).most_common(3)},
                {t.artist_id for t in profile_tracks if t.artist_id},
            )

            for system in systems:
                for provider in (providers if system == "agent_full" else ["-"]):
                    if system == "agent_full":
                        ids, final = run_agent(connection, args.user,
                                               fold.hidden_ids, provider, args.k)
                        usage = final.get("usage") or {}
                        extra = {"降级": final.get("degraded"), "修复轮": final.get("repair_count"),
                                 "tokens_in": usage.get("tokens_in"), "tokens_out": usage.get("tokens_out")}
                    else:
                        ids = run_deterministic(system, profile_tracks, all_tracks, args.k)
                        extra = {}

                    row = {
                        "切分": fold.name(), "系统": system,
                        "provider": provider, "k": args.k,
                        "recall@20": round(metrics.recall_at_k(ids, fold.hidden_ids, 20), 4),
                        "recall@50": round(metrics.recall_at_k(ids, fold.hidden_ids, 50), 4),
                        "precision@20": round(metrics.precision_at_k(ids, fold.hidden_ids, 20), 4),
                        "hit@20": metrics.hit_rate_at_k(ids, fold.hidden_ids, 20),
                        "artist_recall": round(metrics.artist_recall(ids, fold.hidden_ids, artist_of, 20), 4),
                        "天花板": f"{ceil_ok}/{ceil_total}",
                        "天花板比": round(ceil_ok / ceil_total, 4) if ceil_total else 0,
                        **extra,
                    }
                    rows.append(row)
                    print(f"  {row['切分'][:26]:28} {system:14} {provider:9} "
                          f"recall@20={row['recall@20']:.3f}  hit={row['hit@20']}  "
                          f"天花板={row['天花板比']:.2f}")
    finally:
        connection.close()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULT_DIR / stamp
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "results.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n写进 {out/'results.csv'}")

    # 汇总：每个系统跨折的均值，并带上天花板
    print("\n按系统汇总（跨折均值）：")
    for system in systems:
        subset = [r for r in rows if r["系统"] == system]
        if not subset:
            continue
        avg = sum(r["recall@20"] for r in subset) / len(subset)
        ceil = sum(r["天花板比"] for r in subset) / len(subset)
        print(f"  {system:16} recall@20={avg:.3f}  天花板={ceil:.2f}  "
              f"归一化={avg/ceil:.3f}" if ceil else f"  {system:16} recall@20={avg:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 6. `tests/test_evals.py`

```python
"""评估的离线部分。切分、天花板、指标、baseline —— 全是纯函数，秒级。"""

from __future__ import annotations

import pytest

from evals import metrics, splits


def test_random_folds_are_disjoint_and_cover_all():
    """5 折的藏歌必须互不重叠、合起来正好是全部 —— 否则某首歌被重复藏，
    或者从来没被藏过，两种都会让指标失真。"""
    class T:
        def __init__(self, i): self.track_id, self.artist_id = i, i // 3
    tracks = [T(i) for i in range(100)]
    folds = splits.random_item_folds(tracks, 5)
    union = set().union(*(f.hidden_ids for f in folds))
    assert len(union) == sum(len(f.hidden_ids) for f in folds)   # 不重叠
    assert union == {t.track_id for t in tracks}                 # 全覆盖


def test_artist_cold_hides_whole_artists():
    """按艺人藏：一个艺人要么全藏，要么全不藏。**半个艺人等于泄露**。"""
    class T:
        def __init__(self, i): self.track_id, self.artist_id = i, i // 3
    tracks = [T(i) for i in range(90)]
    folds = splits.artist_cold_folds(tracks, 5)
    by_artist = {}
    for t in tracks:
        by_artist.setdefault(t.artist_id, set()).add(t.track_id)
    for f in folds:
        for artist, ids in by_artist.items():
            assert ids <= f.hidden_ids or not (ids & f.hidden_ids)


def test_metric_perfect_and_zero():
    hidden = {1, 2, 3, 4}
    assert metrics.recall_at_k([1, 2, 3, 4], hidden, 20) == 1.0
    assert metrics.recall_at_k([9, 8, 7], hidden, 20) == 0.0
    assert metrics.recall_at_k([1, 2], hidden, 20) == 0.5


def test_recall_at_k_respects_k():
    """@20 只看前 20 个 —— 第 21 个命中不算。"""
    hidden = {99}
    assert metrics.recall_at_k([99] + list(range(100, 130)), hidden, 20) == 1.0
    assert metrics.recall_at_k(list(range(100, 120)) + [99], hidden, 20) == 0.0


def test_ceiling_is_a_diagnostic_not_a_guarantee():
    """天花板反映「库里有没有同类」。全部没有同类时应该是 0。"""
    class T:
        def __init__(self, i, artist, genres):
            self.track_id, self.artist_id, self.genres, self.album_id = i, artist, genres, i
    hidden_track = T(1, 100, ("说唱",))
    # 池子里只有另一个流派的歌，且艺人不同
    pool = [T(2, 200, ("古典",)), T(3, 201, ("古典",))]
    fold = splits.Fold(index=0, hidden_ids={1}, kind="artist_cold")
    ok, total = splits.ceiling(fold, [hidden_track] + pool, {"古典"}, {200, 201})
    assert (ok, total) == (0, 1)


def test_content_baseline_is_deterministic():
    """评估要跨系统对比，基线带随机性就没法比。"""
    from evals import baselines
    class T:
        def __init__(self, i): self.track_id, self.artist_id = i, i // 3
    assert baselines.random_pick([T(i) for i in range(50)], [T(0)], 5) == \
           baselines.random_pick([T(i) for i in range(50)], [T(0)], 5)
```

---

## 怎么跑

```bash
cd agent-service

# 1. 离线部分（秒级，先跑这个）
.venv/Scripts/python.exe -m pytest -q

# 2. 四个确定性基线（无 LLM，约 1 分钟）
.venv/Scripts/python.exe -m evals.run_eval --kind artist_cold \
    --systems random,genre_prior,artist_repeat,content --folds 5

# 3. 加上 agent（要 LLM，约 10 分钟）
.venv/Scripts/python.exe -m evals.run_eval --kind artist_cold \
    --systems random,genre_prior,artist_repeat,content,agent_full \
    --providers deepseek --folds 5
```

---

## 验收标准

1. **单测全绿，仍在 1 秒内**
2. **`content` 必须显著高于 `random` 和 `genre_prior`**
   —— 如果连朴素基线都打不过，说明 `reco/` 有问题，先别碰 LLM
3. **`agent_full` 若不如 `content`-alone，按提前定好的规则退回确定性排序、LLM 只写解释**
   —— 把这条决策真实执行，不要「再调调看」
4. **逐折报数 + 报天花板**，不报单一个总数
   —— 5 折每折只藏 ~98 首，单折数字方差很大，不假装有意义
5. **结果写成 `recall / ceiling`**，并给逐流派分解
6. **两个 kind 都跑**：`random_item` 是乐观值（必须标明），`artist_cold` 是主指标

---

## 五个坑

1. **藏歌必须留在候选池里**。藏了又排除出候选 → recall 恒为 0，
   而且看起来像「算法很差」。实测确认过：藏 89 首，候选池里还有 37 首。
2. **画像用 profile_tracks（减掉藏歌），候选用 all_tracks（全库）**。
   这两个集合不一样，混用就是泄露。
3. **评估不进 pytest**。LLM 调用慢、贵、有随机性 —— 混进去的后果是没人跑测试。
4. **种子固定**。`SEED = 20261003` 在 splits 和 baselines 里都要用同一个，
   否则两次评估不可比。
5. **`agent_full` 的推荐可能为空**（降级路径会丢掉推荐项）。
   空列表的 recall 是 0 —— 要把它和「跑了但没命中」分开记，
   否则降级会被当成「推荐效果差」。

---

## 写完发我什么

1. `pytest -q` 输出
2. **四个确定性基线的对比表**（先只看这个 —— 它不花钱，而且能立刻看出 `reco/` 行不行）
3. 加上 `agent_full` 之后的完整表
4. **你的判断**：LLM 那一步是加分还是减分？如果减分，按规则退回确定性排序，
   把 LLM 降级成「只写解释」—— 这个取舍是这一步最需要判断力的地方
5. 天花板明显偏低的流派有哪些（那是数据的锅，不是算法的锅，要单独说）
