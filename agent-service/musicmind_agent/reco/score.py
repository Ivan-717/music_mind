"""内容相似度打分。

【这个文件是初版，Phase 5 由你重写】写它的目的是让工具层能跑起来、
让评估有个非 LLM 的对照基線 —— 没有这个基线，评估测出来的是
「LLM 脑子里对周杰伦的记忆」，不是这个系统的能力。

三条设计约束，重写时请保留：

1. **确定性**。同样的输入必须给同样的分数。评估要跑 5 折 × 6 个系统，
   任何随机性都会让对比失去意义。

2. **可拆解**。返回值是各分量的字典，不是一个总分。推荐理由要能说
   「因为同流派（0.35）+ 同艺人（0.25）」，而不是「模型觉得像」。
   原则 4 要求推荐可解释，解释的骨架就是这些分量。

3. **权重集中在这一个 dict 里**。评估可以直接网格扫它，不需要改代码。
   分散在各处的魔数就没法扫了。

【为什么不是向量相似度】库里没有任何文本语料（乐评/简介/歌词全无），
embedding 无米下锅。真 embedding 是 Phase 2 RAG 的事。
现在能用的就是这几个结构化信号，命名上要诚实：只能说
「同流派/同期/同艺人」，不能说「语义相似」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from musicmind_agent.evidence import EnrichedTrack

# 权重初值。Phase 5 的评估要在这上面做网格搜索
DEFAULT_WEIGHTS = {
    "genre": 0.30,
    "artist": 0.25,
    "mood": 0.15,      # 只在候选有**实测**音频特征时计入，推断值权重减半
    "era": 0.12,
    "duration": 0.05,
    "form": 0.05,
}

# 新意：推荐一首用户从没听过的艺人，本身有价值（探索），
# 但不能盖过「像他喜欢的」这个主目标，所以单独一项小权重
NOVELTY_LAMBDA = 0.15

# 年代距离的半宽（年）。超过它就认为「不是同一个时期的」
ERA_SCALE = 25.0
# 时长相似度的半宽（毫秒）
DURATION_SCALE_MS = 180_000.0


@dataclass
class TasteProfile:
    """从用户的曲目集合归纳出来的口味画像。打分函数只依赖它，不碰数据库 ——
    这样评估能对同一个 profile 反复打分，不用每次重查。"""

    genre_share: dict[str, float] = field(default_factory=dict)
    top_artists: set[int] = field(default_factory=set)
    known_artists: set[int] = field(default_factory=set)
    known_tracks: set[int] = field(default_factory=set)
    median_year: float | None = None
    median_duration_ms: float | None = None
    form_share: dict[str, float] = field(default_factory=dict)
    mean_arousal: float | None = None


def _triangle(value: float, center: float, half_width: float) -> float:
    """三角核：中心为 1，到半宽处衰减到 0。比硬阈值温和，
    也避免了「差 1 年就完全不算同期」这种台阶。"""
    if half_width <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(value - center) / half_width)


def content_score(
    candidate: EnrichedTrack,
    profile: TasteProfile,
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """给一个候选打分。返回各分量 + 总分，**不是只返回总分**。

    【缺失的数据填 0.5，不做「权重重新分配」】
    这是我实测过的一个反直觉结论。原本的想法是「没数据就不该参与，
    把权重让给有数据的分量」，听起来对，但实测把 random_item 的
    「占上界」从 61.6% 打到了 5.6% —— 因为重新归一化会**抬高稀疏候选的分数**：
    只有 artist 一项适用的候选，除以 0.25 之后拿到满分 1.0，
    比所有分量都算出 0.7 的候选还高。top-k 于是被数据最稀疏的歌填满。

    填 0.5 的代价是「给所有候选加一个常数」—— 常数不影响排序，
    只影响分数的绝对值。那个代价比稀疏偏置小得多。
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    parts: dict[str, float] = {}

    # ---- 流派 ----
    # 取「候选的流派在用户口味里占的最大份额」。
    #
    # 试过改成「份额之和」（理由是最大份额让多标签候选占便宜：
    # ["mandopop","ballad"] 取到 0.68，["ballad"] 只有 0.11）。
    # 实测两个切分都变差了或持平：random_item 61.6% → 55.2%，
    # artist_cold 0.8% → 1.4%。所以保持最大份额，别凭直觉改。
    if candidate.genres and profile.genre_share:
        parts["genre"] = max(
            (profile.genre_share.get(g, 0.0) for g in candidate.genres), default=0.0)
    else:
        parts["genre"] = 0.5

    # ---- 艺人 ----
    if candidate.artist_id in profile.top_artists:
        parts["artist"] = 1.0
    elif candidate.artist_id in profile.known_artists:
        parts["artist"] = 0.6
    else:
        parts["artist"] = 0.0

    # ---- 能量：只在候选有实测特征时算 ----
    if candidate.arousal_measured is not None and profile.mean_arousal is not None:
        parts["mood"] = max(
            0.0, 1.0 - abs(candidate.arousal_measured - profile.mean_arousal))
    else:
        # 【推断值不算进这里】流派推出来的能量粒度太粗（宽流派一律 0.5），
        # 拿它装作「能量相似」是在制造一个假的相似度
        parts["mood"] = 0.5

    # ---- 年代 ----
    year = candidate.year
    if year and profile.median_year is not None:
        parts["era"] = _triangle(year, profile.median_year, ERA_SCALE)
    else:
        parts["era"] = 0.5

    # ---- 时长 ----
    if candidate.duration_ms and profile.median_duration_ms:
        parts["duration"] = _triangle(
            candidate.duration_ms, profile.median_duration_ms, DURATION_SCALE_MS)
    else:
        parts["duration"] = 0.5

    # ---- 专辑形态 ----
    if candidate.primary_type and profile.form_share:
        parts["form"] = profile.form_share.get(candidate.primary_type, 0.0)
    else:
        parts["form"] = 0.5

    base = sum(parts[name] * w[name] for name in w)

    # ---- 新意：没听过的艺人加分 ----
    novelty = 1.0 if candidate.artist_id not in profile.known_artists else 0.0
    parts["novelty"] = novelty

    parts["total"] = base + NOVELTY_LAMBDA * novelty
    return parts


def build_profile(tracks: list[EnrichedTrack],
                  known_artist_ids: set[int] | None = None,
                  known_track_ids: set[int] | None = None) -> TasteProfile:
    """从用户的曲目归纳口味画像。

    【为什么单独一个函数】打分函数必须能对同一个 profile 反复调用（评估要跑
    5 折 × 6 个系统），每次重算 profile 既慢又可能因为顺序不同而不一致。

    【tracks 和 known_* 是两件事】tracks 决定**偏好** —— 流派份额、top 艺人、
    年代中位数。known_* 决定**「你已经有什么」** —— 候选排除 + 探索判定。

    按一张歌单分析时两者不一样：偏好只来自那张歌单，但「已经有」是全部曲库。
    不分开的后果有两个，都不会报错：
      · 候选池只排除那张歌单的歌 → 推荐你在别的歌单里已经有的歌
      · 探索配额把陈奕迅当陌生歌手 → 你在他那儿有 49 首，那一半名额就废了

    **不传 known_* 时两者相同** —— 全量分析和评估走的就是这条路，
    行为一个字节都没变，所以这次的改动不会让评估数字动。
    """
    from collections import Counter

    genre_counter: Counter = Counter()
    artist_counter: Counter = Counter()
    form_counter: Counter = Counter()
    years: list[int] = []
    durations: list[float] = []
    arousals: list[float] = []

    for t in tracks:
        for g in t.genres:
            genre_counter[g] += 1
        if t.artist_id:
            artist_counter[t.artist_id] += 1
        if t.primary_type:
            form_counter[t.primary_type] += 1
        if t.year:
            years.append(t.year)
        if t.duration_ms:
            durations.append(t.duration_ms)
        if t.arousal_measured is not None:
            arousals.append(t.arousal_measured)

    genre_total = sum(genre_counter.values()) or 1
    form_total = sum(form_counter.values()) or 1

    def median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2

    return TasteProfile(
        genre_share={g: c / genre_total for g, c in genre_counter.items()},
        top_artists={a for a, _ in artist_counter.most_common(10)},
        known_artists=(set(known_artist_ids) if known_artist_ids is not None
                       else set(artist_counter)),
        known_tracks=(set(known_track_ids) if known_track_ids is not None
                      else {t.track_id for t in tracks}),
        median_year=median(years),
        median_duration_ms=median(durations),
        form_share={f: c / form_total for f, c in form_counter.items()},
        mean_arousal=median(arousals),
    )
