"""画像素材：从 facts 仓里挑出几条有辨识度的，翻译成**中性的读法**。

【职责怎么分 —— 这是这块唯一的设计点】

    代码负责真实      素材每条都挂着 fact key；报告里的「依据行」由代码渲染，
                      所以它 100% 是 facts 的引用，一个字的形容词都不掺
    LLM 负责好玩      拿素材去写意象（「夜行的猫」），并说明它依据了哪几条

这么分的原因：名字是创作，机器判不了「贴切」；但**机器能保证「引用都是真的」**。
把两件事混在一层里，就会变成让 LLM 既编名字又编依据。

【为什么这里不下「低能量」这种判断】那是形容词，属于 LLM 的活。这一层只给
「0.42（0–1 量纲，归一化区间中点 0.5）」，让读的人自己判断。

唯一的例外是能量档位，而它站得住：arousal 是 `normalize(x, low, high)` 出来的，
**0.5 是区间中点，不是拍的阈值**。占比类的「过半」同理 —— 50% 是客观的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Trait:
    """一条画像素材。"""

    key: str          # fact key —— 依据行靠它渲染，必须是 facts 仓里真有的
    name: str         # 素材名（「能量」「头部流派」），给 LLM 看的
    reading: str      # 中性读法（「0.42，偏静的一侧」）


# 能量的档位。0.5 是归一化区间的中点，**不是调出来的**
_AROUSAL_BANDS = ((0.35, "很静"), (0.50, "偏静"), (0.65, "偏热烈"))
_AROUSAL_TOP = "很热烈"


def _arousal_reading(value: float) -> str:
    band = next((label for edge, label in _AROUSAL_BANDS if value < edge), _AROUSAL_TOP)
    return f"{value:.2f}（0–1 量纲，0.5 是区间中点）→ {band}"


def _share_reading(value: float) -> str:
    """就报百分比，不加「过半 / 不足一半」那种档位词。

    试过加，读起来像废话 ——「薛之谦一个人占 25.0%（不足一半）」里那半句
    没提供任何信息，25% 本身就是全部信息。能量那条不同，0.42 单看没有量纲感，
    所以它保留档位。
    """
    return f"{value * 100:.1f}%"


def _top_by_share(facts: dict[str, Any], prefix: str, skip: tuple[str, ...] = ()) -> tuple[str, float] | None:
    """某个前缀下 share 最大的那条。返回 (fact_key, 值)。

    skip 用来排掉 `artist.top1_share` 这种**名字像但语义不同**的键 ——
    不排的话它会当成某个「叫 top1 的艺人」，而它的值往往最大，一定被选中。
    """
    best: tuple[str, float] | None = None
    for key, value in facts.items():
        if not (key.startswith(prefix) and key.endswith(".share")):
            continue
        if not isinstance(value, (int, float)):
            continue
        mid = key[len(prefix):-len(".share")]
        if mid in skip or not mid:
            continue
        if best is None or value > best[1]:
            best = (key, float(value))
    return best


def _display_name(fact_key: str) -> str:
    """从 fact key 里把名字抠出来。

    【是有损的】`_fact_key` 把空格和 `&` 都换成 `_`，逆不回来 ——
    「contemporary r&b」会变成「contemporary r b」。对报告里那几个头部值
    （mandopop / 薛之谦）没问题，长尾会有点糙。

    优先从工具 rows 里取真名（见 traits_from_facts 的 rows 参数），
    取不到才退回这里。
    """
    parts = fact_key.split(".")
    return parts[-2].replace("_", " ") if len(parts) >= 3 else fact_key


def _genre_display(name: str) -> str:
    """展示层的流派/地区名：繁转简。

    【只转字，不合并条目】「華語流行音樂」和「中文流行音乐」在 Wikidata 是
    两个条目，合不合并是语义判断，展示层不替数据做这个决定 ——
    和繁简政策同一条规矩：存原样（profile 的 facts）、转换只在渲染。
    """
    from zhconv import convert

    return convert(name, "zh-cn")


def _top_shares(facts: dict[str, Any], prefix: str, k: int) -> str:
    """某前缀下 share 最高的 k 条，渲染成「名字（N%）」串。"""
    pool = {key: val for key, val in facts.items()
            if key.startswith(prefix) and key.endswith(".share")
            and isinstance(val, (int, float))}
    top = sorted(pool.items(), key=lambda kv: -kv[1])[:k]
    return "、".join(f"{_genre_display(_display_name(key))}（{val:.0%}）"
                     for key, val in top)


def _row_names(tool_results: dict | None, tool: str, field: str) -> dict[str, str]:
    """从某个工具的输出里捞「曲目数 → 真名」的映射，用来修正 _display_name 的有损还原。

    genre_distribution 的 rows 是 {来源, 流派, 曲目数, 占比}；
    artist_affinity 的是 {艺人, 曲目数, 占比}。拿曲目数当键去对 ——
    事实的键名是 _fact_key 洗过的（空格和 & 都变 _），逆不回来，
    但工具行里存的是真名。
    """
    if not tool_results:
        return {}
    result = tool_results.get(tool) or {}
    rows = result.get("rows") if isinstance(result, dict) else getattr(result, "rows", None)
    out: dict[str, str] = {}
    for row in rows or []:
        if field in row:
            out[str(row.get("曲目数"))] = str(row[field])
    return out


def _name_for(fact_key: str, facts: dict[str, Any], names: dict[str, str]) -> str:
    """真名优先，退回归属键名。

    fact 里同时有 `<前缀>.<名字>.tracks` 和 `.share`，用 tracks 去对行里的「曲目数」。
    """
    tracks = facts.get(fact_key.replace(".share", ".tracks"))
    if tracks is not None and str(tracks) in names:
        return names[str(tracks)]
    return _display_name(fact_key)


def traits_from_facts(facts: dict[str, Any],
                      tool_results: dict | None = None,
                      limit: int = 7) -> list[Trait]:
    """挑素材。按辨识度排序，最多 limit 条；facts 里没有的直接跳过。

    【limit 为什么是 7 不是 6】「未入库那半边」这一段排在 7 条候选的第 7 位
    （能量/头部流派/头部艺人/年代/口味宽度/探索度/未入库）—— limit=6 时
    它被截掉，而它讲的是真实用户 64% 的曲目（实测 user 34：791/1234），
    是画像里最大的一块结构信息。加到 7 让它出得来，不改任何既有排序。

    **不编任何一条。** 某个维度没数据（比如没有实测音频特征）就不出这条素材，
    而不是给个默认值 —— 素材少几条，名字顶多朴素一点；编一条出去，
    整份报告的可信度就没了。
    """
    traits: list[Trait] = []

    # ---- 能量（实测）----
    arousal = facts.get("mood.arousal_mean")
    if isinstance(arousal, (int, float)):
        measured = facts.get("mood.measured_tracks")
        # 【没有实测数就不提实测】写成「0 首是实测的」是**误导** ——
        # 那句话读起来像「一首实测都没有」，而真实情况是这条 fact 不在仓里
        note = (f"（{measured} 首是 30 秒音频实测的，其余按流派推断）"
                if measured is not None else "")
        traits.append(Trait(
            key="mood.arousal_mean", name="能量",
            reading=f"{_arousal_reading(float(arousal))}{note}",
        ))

    # ---- 头部流派（专辑级优先，它比艺人级精确）----
    genre_names = _row_names(tool_results, "genre_distribution", "流派")
    top_genre = _top_by_share(facts, "genre.album.")
    if top_genre:
        key, value = top_genre
        name = _name_for(key, facts, genre_names)
        traits.append(Trait(
            key=key, name="头部流派",
            reading=f"{name} 的占比 {_share_reading(value)}（专辑级口径）",
        ))

    # ---- 头部艺人 ----
    artist_names = _row_names(tool_results, "artist_affinity", "艺人")
    top_artist = _top_by_share(facts, "artist.", skip=("top1", "top5"))
    if top_artist:
        key, value = top_artist
        name = _name_for(key, facts, artist_names)
        traits.append(Trait(
            key=key, name="头部艺人",
            reading=f"{name} 一个人占 {_share_reading(value)}",
        ))

    # ---- 年代 ----
    median_year = facts.get("era.median_year")
    if isinstance(median_year, (int, float)):
        span = ""
        lo, hi = facts.get("scope.year_min"), facts.get("scope.year_max")
        if lo and hi:
            span = f"，跨度 {lo}–{hi}"
        traits.append(Trait(
            key="era.median_year", name="年代",
            reading=f"发行年中位数 {int(median_year)}{span}",
        ))

    # ---- 集中度 / 探索度 ----
    entropy = facts.get("diversity.genre_entropy")
    if isinstance(entropy, (int, float)):
        traits.append(Trait(
            key="diversity.genre_entropy", name="口味宽度",
            reading=f"流派熵 {float(entropy):.2f}（0 = 只听一种，1 = 完全均匀）",
        ))

    singleton = facts.get("diversity.singleton_artist_share")
    if isinstance(singleton, (int, float)):
        traits.append(Trait(
            key="diversity.singleton_artist_share", name="探索度",
            reading=f"只出现过一次的艺人占 {_share_reading(float(singleton))}",
        ))

    # ---- 未入库的那半边 ----
    # 中文说唱/冷门歌有近一半对齐不上 MB，但那半边的人是真实听着的。
    # 素材里明说，名字/开场白才可能把「半个人的画像」补回来。
    un_tracks = facts.get("unmatched.tracks")
    if isinstance(un_tracks, (int, float)) and un_tracks:
        who = ""
        top_un = _top_by_share(facts, "unmatched.artist.")
        if top_un:
            key, _ = top_un
            who = f"，最常见的还是 {_display_name(key)}"
        reading = f"歌单里另有 {int(un_tracks)} 首没入库（MusicBrainz 上大多没有）{who}"
        # 层 2（Wikidata 补的流派/地区）**并进这条，不单开素材** ——
        # 素材默认只取 6 条，单开一条会排在第 7-8 位被截掉、根本出不来；
        # 未入库流派的覆盖率只有 ~1/4，文案必须带「有据可查的 N 首」，
        # 不写限定词读的人会以为这半边全都识别了，那是静默夸大。
        un_gen = facts.get("unmatched.genre.tracks")
        if isinstance(un_gen, (int, float)) and un_gen:
            reading += (f"。有据可查的 {int(un_gen)} 首以"
                        f"{_top_shares(facts, 'unmatched.genre.', 3)}为主")
            if facts.get("unmatched.country.tracks"):
                reading += f"（艺人多来自 {_top_shares(facts, 'unmatched.country.', 2)}）"
        traits.append(Trait(
            key="unmatched.tracks", name="未入库",
            reading=reading,
        ))

    # 未入库那半边的年代（发行年是导入时补抓的）——和库内的中位数对比着看
    un_year = facts.get("unmatched.era.median_year")
    if isinstance(un_year, (int, float)) and un_year:
        traits.append(Trait(
            key="unmatched.era.median_year", name="未入库年代",
            reading=f"没入库的那半边，发行年中位数 {int(un_year)}",
        ))

    # 歌单标签（用户建的歌单才有；榜单类没有）。粗粒度但真实
    tag_facts = {k: v for k, v in facts.items()
                 if k.startswith("unmatched.tag.") and k.endswith(".playlists")}
    if tag_facts:
        top_tags = sorted(tag_facts.items(), key=lambda kv: -kv[1])[:3]
        names = "、".join(_display_name(k) for k, _ in top_tags)
        traits.append(Trait(
            key=top_tags[0][0], name="歌单标签",
            reading=f"你建的歌单带着这些标签：{names}",
        ))

    return traits[:limit]


def basis_line(traits: list[Trait], facts: dict[str, Any]) -> str:
    """「依据行」。**由代码渲染，不是 LLM 写的** —— 这是它可信的全部理由。

    每条渲染成 `素材名 真值`，真值直接从 facts 取（不经过 LLM 的手）。

    【数值渲染复用 render.format_metric】不自己写一遍 —— 那个函数的规矩是
    `share`/`ratio` 渲染成百分比、`lift` 渲染成「N 倍」，报告正文走的是它。
    两处各写一份的话，同一个数字在标题下和正文里会长得不一样
    """
    from musicmind_agent.render import format_metric

    parts = []
    for trait in traits:
        value = facts.get(trait.key)
        if value is None:
            continue
        text = format_metric(trait.key, value) if isinstance(value, (int, float)) else str(value)
        parts.append(f"{trait.name} {text}")
    return " · ".join(parts)


def render_traits(traits: list[Trait]) -> str:
    """素材表，直接进 prompt。带 fact key —— LLM 要照着它填 used_facts。"""
    lines = []
    for i, trait in enumerate(traits, start=1):
        lines.append(f"{i}. {trait.name} —— `{trait.key}` = {trait.reading}")
    return "\n".join(lines) if lines else "（这一轮没有可用的素材，名字写朴素一点）"
