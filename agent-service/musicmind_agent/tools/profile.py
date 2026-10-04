"""Tier 0 核心工具：每次报告必跑，不经 LLM 决定。

【为什么核心维度不让 Agent 自己选】两次运行必须可比，否则评估没有基座。
如果某次模型漏调了年代维度，报告会静悄悄缺一块，而没有任何东西会报警。
Agent 的自由度保留在 Tier 1 探针（额外查什么）和叙事上。

这些工具全是纯 Python 聚合 —— 数据已经被 evidence.load_enriched 一次取全了，
不用再写 SQL，也就不会出现「同一个分母在五个工具里算法不一样」。
"""

from __future__ import annotations

import math
from collections import Counter

from musicmind_agent.evidence import MIN_ARTISTS, MIN_TRACKS
from musicmind_agent.tools.base import (
    ToolContext,
    ToolResult,
    cap_evidence,
    cov,
    register,
)

# 推断值的置信度权重。低置信度的流派（mandopop 这种）几乎不参与 ——
# 用它们推情绪等于没推，给个小权重比假装有用诚实
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.2}


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _entropy(counter: Counter) -> float:
    """归一化香农熵。0 = 只听一个流派，1 = 完全均匀。"""
    total = sum(counter.values())
    if total <= 0 or len(counter) <= 1:
        return 0.0
    raw = -sum((n / total) * math.log(n / total) for n in counter.values())
    return raw / math.log(len(counter))


# ============================================================
# 总览：所有分母的来源 + 数据不足守卫
# ============================================================

@register(
    "user_evidence_overview", 0,
    "用户的曲目规模、各信号覆盖率、数据跨度。所有百分比的分母都来自这里",
)
def user_evidence_overview(ctx: ToolContext, args: dict) -> ToolResult:
    tracks = ctx.tracks
    total = len(tracks)

    with_album_genre = sum(1 for t in tracks if t.album_genres)
    with_artist_genre = sum(1 for t in tracks if t.artist_genres)
    with_genre = sum(1 for t in tracks if t.genres)
    with_year = sum(1 for t in tracks if t.year)
    with_arousal = sum(1 for t in tracks if t.arousal_measured is not None)
    artists = {t.artist_id for t in tracks if t.artist_id}
    albums = {t.album_id for t in tracks if t.album_id}

    years = [t.year for t in tracks if t.year]

    ctx.fact("scope.tracks", total)
    ctx.fact("scope.artists", len(artists))
    ctx.fact("scope.albums", len(albums))
    ctx.fact("scope.favorites", len(ctx.evidence.favorite_ids))
    ctx.fact("scope.playlist_matched", len(ctx.evidence.playlist_ids))
    ctx.fact("coverage.genre", with_genre)
    ctx.fact("coverage.genre_ratio", round(with_genre / total, 4) if total else 0)
    ctx.fact("coverage.genre_via_album", with_album_genre)
    ctx.fact("coverage.genre_via_artist", with_artist_genre)
    # 比例也要给全 —— 只给绝对数的话模型得自己算，实测它把
    # coverage.genre_ratio（89.5%，任一来源）当成了专辑级的覆盖率（实际 31%），
    # 写出「专辑级只覆盖 139 首（占全库 89.5%）」这种自相矛盾的句子
    ctx.fact("coverage.genre_via_album_ratio", round(with_album_genre / total, 4) if total else 0)
    ctx.fact("coverage.genre_via_artist_ratio", round(with_artist_genre / total, 4) if total else 0)
    ctx.fact("coverage.year_ratio", round(with_year / total, 4) if total else 0)
    ctx.fact("coverage.year", with_year)
    ctx.fact("coverage.arousal_measured", with_arousal)
    ctx.fact("coverage.arousal_measured_ratio", round(with_arousal / total, 4) if total else 0)
    if years:
        ctx.fact("scope.year_min", min(years))
        ctx.fact("scope.year_max", max(years))

    warnings = []
    if total < MIN_TRACKS or len(artists) < MIN_ARTISTS:
        warnings.append(
            f"数据不足以生成画像：{total} 首曲目 / {len(artists)} 位艺人"
            f"（门槛是 {MIN_TRACKS} 首 / {MIN_ARTISTS} 位）"
        )

    return ToolResult(
        tool="user_evidence_overview",
        facts={
            "scope.tracks": total,
            "scope.artists": len(artists),
            "scope.albums": len(albums),
            "scope.favorites": len(ctx.evidence.favorite_ids),
            "scope.playlist_matched": len(ctx.evidence.playlist_ids),
            "coverage.genre_ratio": round(with_genre / total, 4) if total else 0,
            "coverage.arousal_measured_ratio": round(with_arousal / total, 4) if total else 0,
        },
        rows=[{
            "曲目数": total,
            "艺人数": len(artists),
            "专辑数": len(albums),
            "有流派": f"{with_genre} ({with_genre / total * 100:.0f}%)" if total else "0",
            "  其中经专辑": with_album_genre,
            "  其中经艺人": with_artist_genre,
            "有发行年": with_year,
            "有实测音频特征": with_arousal,
            "年代跨度": f"{min(years)}–{max(years)}" if years else "无",
        }],
        coverage=cov(total, with_genre, "流派覆盖率是后面所有流派结论的分母"),
        warnings=warnings,
    )


# ============================================================
# 流派
# ============================================================

@register(
    "genre_distribution", 0,
    "用户的流派分布。**专辑级和艺人级分开报** —— 两者精度差别很大，混在一起会失真",
    {"top_n": "每个来源返回前 N 个流派，默认 8"},
)
def genre_distribution(ctx: ToolContext, args: dict) -> ToolResult:
    top_n = int(args.get("top_n", 8))
    tracks = ctx.tracks
    total = len(tracks)

    album_counter: Counter = Counter()
    artist_counter: Counter = Counter()
    examples: dict[str, list] = {}

    for t in tracks:
        for g in t.album_genres:
            album_counter[g] += 1
            _remember(examples, g, t)
        for g in t.artist_genres:
            artist_counter[g] += 1
            _remember(examples, g, t)

    with_album = sum(1 for t in tracks if t.album_genres)
    with_artist = sum(1 for t in tracks if t.artist_genres)

    # 【为什么必须分开报】实测教训：合并成一个分布时
    #     mandopop 73.2%
    # 而只按专辑级算是 37.3%。因为 mandopop 挂在 229 个艺人上，
    # 等于「这是中文歌」的同义词，区分度接近零，却把具体流派全盖住了。
    # 专辑级是 MusicBrainz 用户按专辑挑的描述性标签（精确、覆盖低），
    # 艺人级是「这个人做什么音乐」（宽、覆盖高）—— 两种信息，不是一个分布。
    album_top = album_counter.most_common(top_n)
    artist_top = artist_counter.most_common(top_n)

    # 全库基准，用来算 lift
    library = ctx.library_genre_counts
    library_total = sum(library.values()) or 1

    def lift(name: str) -> float | None:
        """用户占比 ÷ 全库占比。

        【为什么光看占比不够】实测：mandopop 占 68% 看起来是压倒性的结论，
        但全库基准本来就 30% —— 2.3 倍才是真实信息量。反过来 hip hop
        用户占 7.2%、全库 6.2%，看起来「用户爱听说唱」，其实只高 1.2 倍。
        没有基准的百分比会把「库本身的构成」当成「用户的偏好」。
        """
        base = library.get(name, 0) / library_total
        if base <= 0:
            return None
        return round((album_counter.get(name, 0) / with_album) / base, 2) if with_album else None

    facts = {
        "genre.distinct_album_level": len(album_counter),
        "genre.distinct_artist_level": len(artist_counter),
    }
    for name, count in album_top:
        key = _fact_key(name)
        facts[f"genre.album.{key}.tracks"] = count
        facts[f"genre.album.{key}.share"] = round(count / with_album, 4) if with_album else 0
        value = lift(name)
        if value is not None:
            facts[f"genre.album.{key}.lift"] = value
    for name, count in artist_top:
        key = _fact_key(name)
        facts[f"genre.artist.{key}.tracks"] = count
        facts[f"genre.artist.{key}.share"] = round(count / with_artist, 4) if with_artist else 0

    rows = (
        [{"来源": "专辑", "流派": n, "曲目数": c,
          "占比": f"{c / with_album * 100:.1f}%" if with_album else "0%",
          "对全库倍数": lift(n)}
         for n, c in album_top]
        + [{"来源": "艺人", "流派": n, "曲目数": c,
            "占比": f"{c / with_artist * 100:.1f}%" if with_artist else "0%",
            "对全库倍数": None}
           for n, c in artist_top]
    )

    return ToolResult(
        tool="genre_distribution",
        facts=facts,
        rows=rows,
        evidence=cap_evidence([
            ctx.evidence_for(t, why=f"{name}（{source}级）")
            for source, top in (("专辑", album_top), ("艺人", artist_top))
            for name, _ in top
            for t in examples.get(name, [])
        ]),
        coverage=cov(
            total, with_album,
            "**两个分布的分子分母不同，不能放在一起比**："
            f"专辑级 {with_album} 首、艺人级 {with_artist} 首，各自算占比。"
            "同一首歌可以有多个流派，占比之和会超过 100%（这不是划分）。"
            "**专辑级精确但稀疏，艺人级覆盖广但宽流派（mandopop 这类）区分度低**",
        ),
    )


def _remember(examples: dict[str, list], genre: str, track) -> None:
    bucket = examples.setdefault(genre, [])
    if len(bucket) < 5 and track not in bucket:
        bucket.append(track)


def _fact_key(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name)[:32]


# ============================================================
# 年代
# ============================================================

@register(
    "era_distribution", 0,
    "用户的发行年代分布。用专辑发行年，不是用户什么时候开始听的",
    {"bucket": "分组粒度：decade 或 5y，默认 5y"},
)
def era_distribution(ctx: ToolContext, args: dict) -> ToolResult:
    bucket = args.get("bucket", "5y")
    width = 10 if bucket == "decade" else 5

    tracks = ctx.tracks
    total = len(tracks)
    years = [t.year for t in tracks if t.year]

    grouped: Counter = Counter()
    examples: dict[int, list] = {}
    for t in tracks:
        if not t.year:
            continue
        key = (t.year // width) * width
        grouped[key] += 1
        examples.setdefault(key, [])
        if len(examples[key]) < 3 and t not in examples[key]:
            examples[key].append(t)

    facts = {"era.bucket_years": width}
    for key, count in sorted(grouped.items()):
        facts[f"era.{key}.tracks"] = count
        facts[f"era.{key}.share"] = round(count / total, 4) if total else 0
    if years:
        facts["era.median_year"] = int(_median(years) or 0)
        facts["era.year_min"] = min(years)
        facts["era.year_max"] = max(years)

    return ToolResult(
        tool="era_distribution",
        facts=facts,
        rows=[
            {"年代": f"{key}–{key + width - 1}", "曲目数": count,
             "占比": f"{count / total * 100:.1f}%" if total else "0%"}
            for key, count in sorted(grouped.items())
        ],
        evidence=cap_evidence([
            ctx.evidence_for(t, why=f"{key} 年代")
            for key in sorted(grouped)
            for t in examples.get(key, [])
        ]),
        coverage=cov(
            total, len(years),
            "发行年缺失的曲目不参与。年代反映的是作品什么时候发行，"
            "不是用户什么时候在听 —— 库里没有播放行为数据",
        ),
    )


# ============================================================
# 艺人
# ============================================================

@register(
    "artist_affinity", 0,
    "最常出现的艺人，以及他们的集中度",
    {"limit": "返回前 N 位，默认 10"},
)
def artist_affinity(ctx: ToolContext, args: dict) -> ToolResult:
    limit = int(args.get("limit", 10))
    tracks = ctx.tracks
    total = len(tracks)

    counts: Counter = Counter()
    names: dict[int, str] = {}
    examples: dict[int, list] = {}
    for t in tracks:
        if not t.artist_id:
            continue
        counts[t.artist_id] += 1
        names[t.artist_id] = t.artist_name or "?"
        examples.setdefault(t.artist_id, [])
        if len(examples[t.artist_id]) < 5:
            examples[t.artist_id].append(t)

    top = counts.most_common(limit)
    facts = {"artist.distinct": len(counts)}
    for artist_id, count in top:
        # 艺人名可能带空格和引号，dotted key 只保留字母数字下划线
        key = "".join(ch if ch.isalnum() else "_" for ch in names[artist_id])[:24]
        facts[f"artist.{key}.tracks"] = count
        facts[f"artist.{key}.share"] = round(count / total, 4) if total else 0
    if top:
        facts["artist.top1_share"] = round(top[0][1] / total, 4) if total else 0
        facts["artist.top5_share"] = round(sum(c for _, c in counts.most_common(5)) / total, 4) if total else 0

    return ToolResult(
        tool="artist_affinity",
        facts=facts,
        rows=[
            {"艺人": names[a], "曲目数": c,
             "占比": f"{c / total * 100:.1f}%" if total else "0%"}
            for a, c in top
        ],
        evidence=cap_evidence([
            ctx.evidence_for(t, why=f"{names[a]} 的作品")
            for a, _ in top
            for t in examples.get(a, [])
        ]),
        coverage=cov(total, total, "每首歌都有主艺人，这一项没有缺失"),
    )


# ============================================================
# 多样性 / 探索度
# ============================================================

@register(
    "taste_diversity", 0,
    "口味集中度与探索度：流派熵、头部占比、艺人重复度、与全库分布的偏离",
)
def taste_diversity(ctx: ToolContext, args: dict) -> ToolResult:
    tracks = ctx.tracks
    total = len(tracks)

    genre_counter: Counter = Counter()
    artist_counter: Counter = Counter()
    for t in tracks:
        for g in t.genres:
            genre_counter[g] += 1
        if t.artist_id:
            artist_counter[t.artist_id] += 1

    genre_total = sum(genre_counter.values())
    entropy = _entropy(genre_counter)
    top1_share = (genre_counter.most_common(1)[0][1] / genre_total) if genre_total else 0
    top5_artist_share = (
        sum(c for _, c in artist_counter.most_common(5)) / total if total else 0
    )
    singletons = sum(1 for c in artist_counter.values() if c == 1)
    singleton_share = singletons / len(artist_counter) if artist_counter else 0

    years = [t.year for t in tracks if t.year]
    decades = Counter((y // 10) * 10 for y in years)
    decades_covered = sum(1 for c in decades.values() if c / len(years) > 0.05) if years else 0

    facts = {
        "diversity.genre_entropy": round(entropy, 4),
        "diversity.genre_top1_share": round(top1_share, 4),
        "diversity.artist_top5_share": round(top5_artist_share, 4),
        "diversity.singleton_artist_share": round(singleton_share, 4),
        "diversity.decades_covered": decades_covered,
        "diversity.artists_per_100_tracks": round(len(artist_counter) / total * 100, 1) if total else 0,
    }

    # 与全库分布的偏离：用户是不是只在一个很小的角落里听
    library = ctx.library_genre_counts
    library_total = sum(library.values())
    if library_total and genre_total:
        user_dist = {g: c / genre_total for g, c in genre_counter.items()}
        lib_dist = {g: c / library_total for g, c in library.items()}
        # 拉普拉斯平滑，避免 log(0)
        vocab = set(user_dist) | set(lib_dist)
        eps = 1e-6
        kl = sum(
            (user_dist.get(g, eps)) * math.log((user_dist.get(g, eps)) / (lib_dist.get(g, eps)))
            for g in vocab
        )
        facts["diversity.library_kl"] = round(kl, 4)

    return ToolResult(
        tool="taste_diversity",
        facts=facts,
        rows=[{
            "流派熵": f"{entropy:.2f}（0=只听一种，1=完全均匀）",
            "头部流派占比": f"{top1_share * 100:.0f}%",
            "前 5 艺人占比": f"{top5_artist_share * 100:.0f}%",
            "只出现一次的艺人": f"{singleton_share * 100:.0f}%",
            "覆盖的十年数": decades_covered,
            "每百首歌的艺人数": facts["diversity.artists_per_100_tracks"],
        }],
        evidence=[],
        coverage=cov(total, genre_total and total or 0,
                    "熵和集中度都基于流派；没有流派的歌不参与这两个数"),
    )


# ============================================================
# 情绪 / 能量
# ============================================================

@register(
    "mood_energy_profile", 0,
    "音乐能量分布。【能量是实测的，效价是流派推断的】两者覆盖率分开报",
)
def mood_energy_profile(ctx: ToolContext, args: dict) -> ToolResult:
    tracks = ctx.tracks
    total = len(tracks)

    measured = [t for t in tracks if t.arousal_measured is not None]
    inferred_tracks: list[tuple] = []      # (track, arousal, valence, weight, confidence)

    for t in tracks:
        if t.arousal_measured is not None:
            continue
        entries = [(g, ctx.mood_map.get(g)) for g in t.genres]
        entries = [(g, m) for g, m in entries if m]
        if not entries:
            continue
        weight_sum = sum(m["weight"] for _, m in entries)
        if weight_sum <= 0:
            continue
        arousal = sum(m["arousal"] * m["weight"] for _, m in entries) / weight_sum
        valence = sum(m["valence"] * m["weight"] for _, m in entries) / weight_sum
        # 整首歌的置信度取最强的那条流派
        best = max(entries, key=lambda x: x[1]["weight"])[1]["confidence"]
        inferred_tracks.append((t, arousal, valence, weight_sum, best))

    measured_arousal = [t.arousal_measured for t in measured]
    inferred_arousal = [a for _, a, _, _, _ in inferred_tracks]
    all_arousal = measured_arousal + inferred_arousal

    facts = {
        "mood.measured_tracks": len(measured),
        "mood.inferred_tracks": len(inferred_tracks),
        "mood.unknown_tracks": total - len(measured) - len(inferred_tracks),
    }
    if measured_arousal:
        facts["mood.arousal_measured_mean"] = round(sum(measured_arousal) / len(measured_arousal), 4)
        facts["mood.arousal_measured_min"] = round(min(measured_arousal), 4)
        facts["mood.arousal_measured_max"] = round(max(measured_arousal), 4)
    if all_arousal:
        facts["mood.arousal_mean"] = round(sum(all_arousal) / len(all_arousal), 4)
        facts["mood.arousal_median"] = round(_median(all_arousal) or 0, 4)
    if inferred_arousal:
        facts["mood.arousal_inferred_mean"] = round(sum(inferred_arousal) / len(inferred_arousal), 4)

    # 效价**只有推断**，必须说清楚
    valences = [v for _, _, v, _, _ in inferred_tracks]
    if valences:
        facts["mood.valence_inferred_mean"] = round(sum(valences) / len(valences), 4)
        facts["mood.valence_is_measured"] = 0
    strong = sum(1 for *_, c in inferred_tracks if c in ("high", "medium"))
    facts["mood.inferred_high_confidence_tracks"] = strong

    bands = Counter()
    for a in all_arousal:
        bands[f"{int(a * 5) / 5:.1f}"] += 1

    def sample(pool, why, n=5):
        picked = sorted(pool, key=lambda x: x.arousal_measured)[:n]
        return [ctx.evidence_for(t, why=why) for t in picked]

    return ToolResult(
        tool="mood_energy_profile",
        facts=facts,
        rows=[
            {"实测音频特征": f"{len(measured)} 首（{len(measured) / total * 100:.0f}%）"},
            {"按流派推断": f"{len(inferred_tracks)} 首（{len(inferred_tracks) / total * 100:.0f}%）"},
            {"  其中推断置信度 high/medium": strong},
            {"完全未知": total - len(measured) - len(inferred_tracks)},
            {"平均能量": facts.get("mood.arousal_mean", "—")},
            {"效价": f"推断均值 {facts.get('mood.valence_inferred_mean', '—')} —— **音频算不出效价**"},
        ],
        evidence=cap_evidence(
            sample(measured, "实测：低能量") +
            sample([t for t in measured if t.arousal_measured and t.arousal_measured > 0.6], "实测：高能量")
        ),
        coverage=cov(
            total, len(measured),
            "**能量是实测的（30 秒音频算的），效价是流派推断的** —— "
            "后者粒度粗，宽流派（mandopop 这类）推出来等于中性。"
            "报告里不允许把推断值当实测值说",
        ),
    )
