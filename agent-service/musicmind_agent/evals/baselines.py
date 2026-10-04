"""四个确定性对照系统。零 LLM、零成本，但必须有。

【没有它们，你测的是「LLM 脑子里对周杰伦的记忆」，不是这个系统。】
"""

from __future__ import annotations

import random
from collections import Counter

from musicmind_agent.evidence import EnrichedTrack
from musicmind_agent.reco.recall import recommend, recall
from musicmind_agent.evals.splits import SEED          # 和切分用同一个种子
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