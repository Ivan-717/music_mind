"""Tier 1 探针：LLM 从白名单里挑着跑，额度 6 次。

【为什么这些不让 LLM 自由发挥】工具名和参数都是固定的，LLM 只做「选哪个、
传什么参数」。它不能凭空发明一个工具 —— plan 节点返回的名字不在白名单里
就直接丢弃（不报错、不重试），这是跨模型稳的关键：DeepSeek 和千问都能
稳定做「从给定列表里选」，但自由生成工具名和参数格式则各有各的毛病。
"""

from __future__ import annotations

from collections import Counter

from musicmind_agent.evidence import load_all_enriched
from musicmind_agent.reco.recall import recommend
from musicmind_agent.tools.base import ToolContext, ToolResult, cap_evidence, cov, register


# ============================================================
# 专辑形态
# ============================================================

@register(
    "album_form_distribution", 1,
    "专辑形态分布（专辑/单曲/EP）。看用户是「专辑型听众」还是「单曲型听众」",
)
def album_form_distribution(ctx: ToolContext, args: dict) -> ToolResult:
    tracks = ctx.tracks
    total = len(tracks)
    counter: Counter = Counter(t.primary_type for t in tracks if t.primary_type)
    examples: dict[str, list] = {}
    for t in tracks:
        if t.primary_type:
            examples.setdefault(t.primary_type, [])
            if len(examples[t.primary_type]) < 3:
                examples[t.primary_type].append(t)

    facts = {"form.distinct": len(counter)}
    for name, count in counter.most_common():
        key = name.lower().replace(" ", "_")
        facts[f"form.{key}.tracks"] = count
        facts[f"form.{key}.share"] = round(count / total, 4) if total else 0

    return ToolResult(
        tool="album_form_distribution",
        facts=facts,
        rows=[
            {"形态": name, "曲目数": count,
             "占比": f"{count / total * 100:.1f}%" if total else "0%"}
            for name, count in counter.most_common()
        ],
        evidence=cap_evidence([
            ctx.evidence_for(t, why=f"{name}")
            for name in counter
            for t in examples.get(name, [])
        ]),
        coverage=cov(total, sum(counter.values()),
                     "形态来自专辑的 primary_type。没有专辑关联的曲目不参与"),
    )


# ============================================================
# 时长
# ============================================================

@register(
    "duration_profile", 1,
    "曲目时长分布。诚实定位：它是流派的冗余信号，不是「音乐能量」",
)
def duration_profile(ctx: ToolContext, args: dict) -> ToolResult:
    tracks = ctx.tracks
    total = len(tracks)
    durations = [(t, t.duration_ms) for t in tracks if t.duration_ms]

    buckets: Counter = Counter()
    examples: dict[str, list] = {}
    for t, ms in durations:
        minutes = ms / 60_000
        key = f"{int(minutes)}–{int(minutes) + 1} 分钟"
        buckets[key] += 1
        examples.setdefault(key, [])
        if len(examples[key]) < 2:
            examples[key].append(t)

    seconds = sorted(ms / 1000 for _, ms in durations)
    facts = {"duration.count": len(seconds)}
    if seconds:
        facts["duration.median_seconds"] = round(seconds[len(seconds) // 2], 1)
        facts["duration.min_seconds"] = round(seconds[0], 1)
        facts["duration.max_seconds"] = round(seconds[-1], 1)

    return ToolResult(
        tool="duration_profile",
        facts=facts,
        rows=[
            {"时长": key, "曲目数": count}
            for key, count in sorted(buckets.items(), key=lambda x: int(x[0].split("–")[0]))
        ],
        evidence=cap_evidence([
            ctx.evidence_for(t, why=key) for key in buckets for t in examples.get(key, [])
        ]),
        coverage=cov(total, len(seconds),
                     "**别把它当能量** —— 长歌不等于慢歌。"
                     "真正的能量用 mood_energy_profile 里实测的那一栏"),
    )


# ============================================================
# 合作网络
# ============================================================

@register(
    "collaboration_network", 1,
    "用户曲目里的合唱关系。既是唯一的「网络」信号，也是推荐的候选来源",
    {"limit": "返回前 N 组，默认 10"},
)
def collaboration_network(ctx: ToolContext, args: dict) -> ToolResult:
    limit = int(args.get("limit", 10))
    track_ids = [t.track_id for t in ctx.tracks]
    if not track_ids:
        return ToolResult(tool="collaboration_network", warnings=["没有曲目"])

    placeholders = ",".join(["%s"] * len(track_ids))
    with ctx.connection.cursor() as cursor:
        # 每首歌的艺人集合。HAVING COUNT(*) >= 2 = 这首歌有合唱
        cursor.execute(
            f"""
            SELECT ta.track_id, COUNT(*) n,
                   GROUP_CONCAT(ar.name ORDER BY ta.id SEPARATOR ' / ') artists
            FROM track_artist ta
            JOIN artist ar ON ar.id = ta.artist_id
            WHERE ta.track_id IN ({placeholders})
            GROUP BY ta.track_id
            HAVING n >= 2
            """,
            track_ids,
        )
        rows = cursor.fetchall()

    pairs: Counter = Counter()
    for row in rows:
        names = sorted(set((row["artists"] or "").split(" / ")))
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pairs[(names[i], names[j])] += 1

    top = pairs.most_common(limit)

    facts = {"collab.tracks_with_multiple_artists": len(rows),
             "collab.distinct_pairs": len(pairs)}
    for (a, b), count in top:
        key = "".join(ch if ch.isalnum() else "_" for ch in f"{a}_{b}")[:40]
        facts[f"collab.{key}.tracks"] = count

    warnings = []
    if not rows:
        warnings.append("这位用户的曲目里没有合唱，这个工具在本次分析中没有信息量")

    return ToolResult(
        tool="collaboration_network",
        facts=facts,
        rows=[{"合作": f"{a} × {b}", "共同曲目数": c} for (a, b), c in top],
        evidence=[],
        coverage=cov(len(ctx.tracks), len(rows),
                     "只在有多个艺人的曲目里找关系。单艺人曲目（大多数）不参与"),
        warnings=warnings,
    )


# ============================================================
# 单个艺人深挖
# ============================================================

@register(
    "artist_deep_dive", 1,
    "深挖一位艺人：他的全部专辑、用户拥有其中几首、流派与合作者",
    {"artist_id": "艺人 id（可以是用户 top 艺人之一）"},
)
def artist_deep_dive(ctx: ToolContext, args: dict) -> ToolResult:
    artist_id = args.get("artist_id")
    if not artist_id:
        return ToolResult(tool="artist_deep_dive", warnings=["需要 artist_id"])
    artist_id = int(artist_id)

    owned = [t for t in ctx.tracks if t.artist_id == artist_id]
    with ctx.connection.cursor() as cursor:
        cursor.execute("SELECT name, country_code, type, begin_year FROM artist WHERE id = %s", (artist_id,))
        artist = cursor.fetchone()
        if not artist:
            return ToolResult(tool="artist_deep_dive", warnings=[f"没有这个艺人：{artist_id}"])
        cursor.execute(
            """
            SELECT al.name, al.release_date, al.primary_type
            FROM album_artist aa JOIN album al ON al.id = aa.album_id
            WHERE aa.artist_id = %s
            ORDER BY al.release_date IS NULL, al.release_date
            LIMIT 30
            """,
            (artist_id,),
        )
        albums = cursor.fetchall()

    owned_album_ids = {t.album_id for t in owned if t.album_id}
    facts = {
        "artist.owned_tracks": len(owned),
        "artist.total_albums_in_library": len(albums),
    }
    if artist["begin_year"]:
        facts["artist.begin_year"] = artist["begin_year"]

    return ToolResult(
        tool="artist_deep_dive",
        facts=facts,
        rows=[{
            "艺人": artist["name"],
            "出身": artist["country_code"] or "未知",
            "类型": artist["type"] or "未知",
            "出道年": artist["begin_year"] or "未知",
            "用户拥有": f"{len(owned)} 首",
            "库内专辑数": len(albums),
            "其中用户听过的": len(owned_album_ids),
        }] + [{"专辑": a["name"], "发行": str(a["release_date"] or "未知"),
               "形态": a["primary_type"] or "?"} for a in albums[:15]],
        evidence=cap_evidence([ctx.evidence_for(t, why="该艺人的作品") for t in owned]),
        coverage=cov(len(owned), len(owned), "只统计用户拥有的曲目"),
    )


# ============================================================
# 地区
# ============================================================

@register(
    "region_distribution", 1,
    "艺人的出身国家/地区分布。**这是艺人出身地，不是音乐风格地区**",
)
def region_distribution(ctx: ToolContext, args: dict) -> ToolResult:
    tracks = ctx.tracks
    total = len(tracks)
    counter: Counter = Counter()
    examples: dict[str, list] = {}
    for t in tracks:
        code = t.country_code or "未知"
        counter[code] += 1
        examples.setdefault(code, [])
        if len(examples[code]) < 3:
            examples[code].append(t)

    known = sum(n for code, n in counter.items() if code != "未知")

    facts = {"region.distinct": len([c for c in counter if c != "未知"])}
    for code, count in counter.most_common(10):
        facts[f"region.{code}.tracks"] = count
        facts[f"region.{code}.share"] = round(count / total, 4) if total else 0

    return ToolResult(
        tool="region_distribution",
        facts=facts,
        rows=[{"地区代码": code, "曲目数": count,
               "占比": f"{count / total * 100:.1f}%" if total else "0%"}
              for code, count in counter.most_common(12)],
        evidence=cap_evidence([
            ctx.evidence_for(t, why=code) for code in counter for t in examples.get(code, [])
        ]),
        coverage=cov(total, known,
                     "**地区码是 ISO 3166（CN/TW/HK/JP…），是艺人的出身地，"
                     "不是音乐风格上的地区**。展示层负责映射成中文。"
                     "库里没有发行地区数据，别把它当发行地"),
    )


# ============================================================
# 找相似曲目
# ============================================================

@register(
    "similar_tracks", 1,
    "按内容相似度找本地库里的曲目。**不是向量相似度**，是流派/年代/艺人/能量的加权",
    {
        "seed_track_ids": "种子曲目 id 列表（通常传用户最喜欢的几首）",
        "limit": "返回条数，默认 20",
        "exclude_track_ids": "要排除的曲目 id（比如已经推荐过的）",
    },
)
def similar_tracks(ctx: ToolContext, args: dict) -> ToolResult:
    seeds = [int(i) for i in (args.get("seed_track_ids") or [])]
    limit = min(int(args.get("limit", 20)), 100)
    exclude = {int(i) for i in (args.get("exclude_track_ids") or [])}

    exclude |= set(seeds)

    # 【和 recommend() 走同一条路，不要另写一套排序】
    # 原来这里是「按内容分排一遍取 top-N」。改成复用 recommend() 之后，
    # 图里的候选列表和评估里的 content 基线是**同一个东西** ——
    # 否则评估测的和线上跑的不是一个算法，那个评估就没有意义。
    #
    # 而且 recommend() 带两个这里原本没有的东西：
    #   · 五路召回（原来只用了内容分一路，同专辑/合作艺人那些路根本没走）
    #   · 探索配额（见 recall.EXPLORE_QUOTA）—— 没有它的话候选会被
    #     「你熟悉的歌手」占满，推荐全是熟人，用户找不到新东西
    #
    # 【known_* 传的是「全部曲库」不是「选中范围」】按一张歌单分析时，
    # 画像来自那张歌单，但候选不能推用户别的歌单里已经有的歌
    all_tracks = load_all_enriched(ctx.connection)
    picked = recommend(ctx.tracks, all_tracks, limit,
                       known_artist_ids=ctx.all_known_artist_ids,
                       known_track_ids=ctx.all_known_track_ids)

    chosen = [item for item in picked if item.track.track_id not in exclude]
    considered = len(all_tracks) - len(ctx.all_known_track_ids)

    facts = {"similar.candidates_considered": considered, "similar.returned": len(chosen)}
    if chosen:
        facts["similar.top_score"] = round(chosen[0].score.get("total", 0), 4)

    return ToolResult(
        tool="similar_tracks",
        facts=facts,
        rows=[{
            "track_id": item.track.track_id, "歌名": item.track.track_name,
            "艺人": item.track.artist_name, "专辑": item.track.album_name,
            "发行年": item.track.year, "流派": list(item.track.genres),
            "能量": item.track.arousal_measured,
            "总分": round(item.score.get("total", 0), 3),
            "分量": {k: round(v, 2) for k, v in item.score.items()
                     if k not in ("total", "mmr_total", "mmr_penalty") and v},
            "召回来源": item.sources,
        } for item in chosen],
        evidence=cap_evidence([
            ctx.evidence_for(item.track, why="内容相似：" + "/".join(item.sources))
            for item in chosen
        ]),
        coverage=cov(considered, considered,
                     "候选集是全库减去用户已知的曲目。"
                     "**打分明细里 mood 那一项在候选没有实测音频特征时是 0.5** —— "
                     "库里绝大多数候选都没有实测特征，所以能量这一项目前区分度很低"
                     "（补全音频特征后才会真正起作用）"),
    )


# ============================================================
# 按条件搜
# ============================================================

@register(
    "search_tracks", 1,
    "按条件在本地库里搜曲目。支持流派、年代、形态、能量区间",
    {
        "genre": "流派名（子串匹配）",
        "year_from": "最早发行年",
        "year_to": "最晚发行年",
        "primary_type": "专辑形态，如 Album / Single",
        "arousal_max": "能量上限（**只对实测过的曲目有效**）",
        "arousal_min": "能量下限",
        "exclude_track_ids": "要排除的曲目 id",
        "limit": "返回条数，默认 20",
    },
)
def search_tracks(ctx: ToolContext, args: dict) -> ToolResult:
    limit = min(int(args.get("limit", 20)), 100)
    exclude = {int(i) for i in (args.get("exclude_track_ids") or [])}
    exclude |= {t.track_id for t in ctx.tracks}      # 默认不推用户已有的

    genre = (args.get("genre") or "").strip().lower()
    year_from = args.get("year_from")
    year_to = args.get("year_to")
    form = (args.get("primary_type") or "").strip()
    arousal_min = args.get("arousal_min")
    arousal_max = args.get("arousal_max")

    candidates = [t for t in load_all_enriched(ctx.connection) if t.track_id not in exclude]
    considered = len(candidates)

    def keep(t) -> bool:
        if genre and not any(genre in g.lower() for g in t.genres):
            return False
        if year_from and (t.year or 0) < int(year_from):
            return False
        if year_to and (t.year or 9999) > int(year_to):
            return False
        if form and (t.primary_type or "") != form:
            return False
        # 能量条件只对实测过的成立 —— 没实测的不能因为「看起来符合」就被选中
        #
        # 【这里曾经写成 t.arousal_measured_measured】多了一截，像是某次
        # arousal → arousal_measured 的批量改名被执行了两遍。它不报语法错，
        # 只在真的传了 energy 区间时才抛 AttributeError，而 call() 会把工具异常
        # 兜成「空结果 + warning」—— 表现是【永远搜不到】，不是报错。
        # 这个字段名改回去之前，整个「推荐一点 emo 的歌」路径是死的
        if arousal_min is not None and (
                t.arousal_measured is None or t.arousal_measured < float(arousal_min)):
            return False
        if arousal_max is not None and (
                t.arousal_measured is None or t.arousal_measured > float(arousal_max)):
            return False
        return True

    hits = [t for t in candidates if keep(t)][:limit]

    return ToolResult(
        tool="search_tracks",
        facts={"search.considered": considered, "search.matched": len(hits)},
        rows=[{
            "track_id": t.track_id, "歌名": t.track_name, "艺人": t.artist_name,
            "专辑": t.album_name, "发行年": t.year, "流派": list(t.genres),
            "能量": t.arousal_measured,
            "能量来源": "实测" if t.arousal_measured is not None else "无",
        } for t in hits],
        evidence=cap_evidence([ctx.evidence_for(t, why="条件命中") for t in hits]),
        coverage=cov(considered, len(hits),
                     "**能量条件只筛实测过的曲目**。库里 4617 首中只有 400 多首有实测特征，"
                     "所以带能量条件的搜索命中数会明显偏少 —— 这是覆盖率的限制，不是没有这样的歌"),
        warnings=(
            ["带能量条件时，候选里绝大多数曲目没有实测特征，会被直接排除"]
            if (arousal_min is not None or arousal_max is not None) else []
        ),
    )
