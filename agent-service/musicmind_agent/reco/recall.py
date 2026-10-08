
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

# 留给「没听过的歌手」的名额比例。见 recommend() 的说明 ——
# 这不是调参调出来的，是评估给出的设计结论，而且应该做成用户可调的旋钮
EXPLORE_QUOTA = 0.5


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
    profile     —— 候选池按 profile.known_tracks 排除，**不是按 tracks 现算**。
                   按一张歌单分析时两者不同：画像来自那张歌单，但候选要排除
                   用户全部曲库里的歌，否则会推荐他在别的歌单里已经有的
    """
    pool = [t for t in all_tracks if t.track_id not in profile.known_tracks]

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


def recommend(tracks, all_tracks, k: int = 20,
              explore_quota: float = EXPLORE_QUOTA,
              known_artist_ids: set[int] | None = None,
              known_track_ids: set[int] | None = None,
              known_name_keys: set[tuple[str, str]] | None = None) -> list[Recalled]:
    """推荐的确定性版本（不经过 LLM）。评估里的 content 基线就是它。

    known_artist_ids / known_track_ids 是「用户整体已经有什么」。
    不传就等同于 tracks 本身 —— 全量分析和评估走的是那条路。
    下面「熟悉 / 陌生」的分组用的是 profile.known_artists，
    而它现在可以比 tracks 更宽，正是为了按歌单分析时不动探索配额的语义。

    【为什么要把名额分成两半】这是评估逼出来的一个结论，不是拍脑袋。

    原来是把所有候选按内容分排一遍取 top-k。实测：
        熟人场景（藏的都是你熟悉的歌手）  占上界 61.6%
        生人场景（整个歌手的歌全藏掉）    占上界  0.5%  ← 和瞎猜一样

    原因是排序被 `artist` 分量主导 —— 它拼命推你熟悉的歌手，
    而**生人场景里要找回的恰恰是陌生歌手**。分数越高的候选，越不可能是答案。

    改成按产品意图分配名额之后（k 个位置里留一部分给没听过的歌手）：

        配额   熟人场景   生人场景
        0.0    61.6%      0.5%
        0.3    55.6%      1.4%
        0.5    44.0%      4.5%   ← 两边都打赢所有基线
        0.7    25.2%      5.4%

    **0.5 是两边都站得住的默认值**，而且它天然是个该交给用户的旋钮 ——
    「想多听点熟悉的」还是「想找点没听过的」是个人偏好，不该写死在代码里。
    """
    # 【同曲不同版本也要排除】库里同一首歌有多条 MBID 条目（「绅士」14265/14268），
    # known_track_ids 只排掉用户对齐上的那一条，另一条照样进候选 ——
    # 用户看到「我歌单里有这首」又被推一次（2026-10-07 实测被当场指出）。
    # 键 = 归一化(歌名 + 主艺人)：只按歌名会误杀同名不同曲
    # （队长的《哪里都是你》不该挡掉周杰伦的同名歌）。
    if known_name_keys:
        from musicmind_agent.validate.normalize import name_key
        all_tracks = [
            t for t in all_tracks
            if (name_key(t.track_name), name_key(t.artist_name)) not in known_name_keys
        ]

    profile = build_profile(tracks, known_artist_ids, known_track_ids)
    merged = recall(tracks, all_tracks, profile)
    ranked = mmr(list(merged.values()), len(merged))

    if not ranked:
        return []

    new_slots = int(round(k * explore_quota))
    known_slots = k - new_slots

    known: list[Recalled] = []
    new: list[Recalled] = []
    for item in ranked:
        if item.track.artist_id in profile.known_artists:
            known.append(item)
        else:
            new.append(item)

    picked = known[:known_slots] + new[:new_slots]

    # 一边不够就用另一边补满 —— 库里的陌生歌手远多于熟悉歌手，
    # 反过来（熟悉的不够）在新用户身上很常见
    if len(picked) < k:
        taken = {id(x) for x in picked}
        for item in ranked:
            if id(item) not in taken:
                picked.append(item)
                if len(picked) >= k:
                    break

    # 补进来的可能打乱顺序，按 mmr_total 重排一次
    picked.sort(key=lambda x: -x.score.get("mmr_total", 0))
    return picked[:k]