"""音乐人格「型」—— 给口味一个稳定的代号。

【为什么是固定池】意象名（「深夜书桌前的一盏台灯」）每次重算都会变，
不稳定的东西当不了名字。型是固定的 22 个，认领后跟着用户走。

【为什么是打分不是布尔】「满足条件才命中」会有 0 命中、或命中一堆分不出高低；
每个型定义一组目标区间，算 0-1 的加权分，取 top3 给人挑。
【缺数据 ≠ 不符合】某条 fact 不在仓里（比如没测过能量）→ 该目标跳过、
权重重新归一，不惩罚也不加分。

【型名是用户筛过的；阈值标了 TBD 的，实现后对着真实报告调】
现有报告的落点：能量 0.42–0.45 / 宽度 0.64 / 中位年 2015。
调完跑 tests/test_persona_types.py 的边界例。
"""

from __future__ import annotations

# ---- 档位（能量 / 宽度 共用的切分）----
A_LOW = (0.0, 0.42)      # 能量低
A_MID = (0.42, 0.55)     # 能量中
A_HIGH = (0.55, 1.0)     # 能量高
E_LOW = (0.0, 0.50)      # 宽度窄（流派集中）
E_MID = (0.50, 0.70)     # 宽度中
E_HIGH = (0.70, 1.0)     # 宽度宽（杂食）


# ---- 22 个型 ----
# targets 的值是 (下界, 上界, 权重)：落在区间内满分，界外按到界的距离线性衰减。
# 权重没有归一要求，同型内相对大小有意义（2.0 是主特征，1.0 是修饰）。
TYPES: list[dict] = [
    # ===== A. 能量 × 宽度（主组合，9 个）=====
    {"name": "守夜人", "desc": "灯只开一盏，音量不大，听得久",
     "targets": {"mood.arousal_mean": (*A_LOW, 2.0),
                 "diversity.genre_entropy": (*E_LOW, 1.0)}},
    {"name": "壁炉边的猫", "desc": "晒着听的歌，不赶时间",
     "targets": {"mood.arousal_mean": (*A_LOW, 2.0),
                 "diversity.genre_entropy": (*E_MID, 1.0)}},
    {"name": "深夜漫游者", "desc": "什么都听，但都听得很轻",
     "targets": {"mood.arousal_mean": (*A_LOW, 2.0),
                 "diversity.genre_entropy": (*E_HIGH, 1.0)}},
    {"name": "老唱片店的常客", "desc": "柜台上那几张，翻了十几年",
     "targets": {"mood.arousal_mean": (*A_MID, 2.0),
                 "diversity.genre_entropy": (*E_LOW, 1.0)}},
    {"name": "温吞的听者", "desc": "不炸不闷，一杯温水",
     "targets": {"mood.arousal_mean": (*A_MID, 2.0),
                 "diversity.genre_entropy": (*E_MID, 1.0)}},
    {"name": "杂货铺老板", "desc": "货架上什么都有，什么都卖一点",
     "targets": {"mood.arousal_mean": (*A_MID, 2.0),
                 "diversity.genre_entropy": (*E_HIGH, 1.0)}},
    {"name": "单曲循环怪", "desc": "一首歌能听一年，一个歌手能听十年",
     "targets": {"mood.arousal_mean": (*A_HIGH, 2.0),
                 "diversity.genre_entropy": (*E_LOW, 1.0)}},
    {"name": "高速公路", "desc": "适合开车、赶稿、跑起来的那种",
     "targets": {"mood.arousal_mean": (*A_HIGH, 2.0),
                 "diversity.genre_entropy": (*E_MID, 1.0)}},
    {"name": "隔壁的 DJ", "desc": "什么都放，放什么都有人跟着摇",
     "targets": {"mood.arousal_mean": (*A_HIGH, 2.0),
                 "diversity.genre_entropy": (*E_HIGH, 1.0)}},

    # ===== B. 年代（3 个）=====
    {"name": "考古学家", "desc": "新歌？先把老歌听完",
     "targets": {"era.median_year": (0.0, 2010.0, 2.0)}},
    {"name": "追新猎手", "desc": "新专辑发行当天就听",
     "targets": {"era.median_year": (2023.0, 3000.0, 2.0)}},
    {"name": "时光旅行者", "desc": "从七零年代一路听过来，跨度比谁都大",
     "targets": {"diversity.decades_covered": (5.0, 99.0, 2.0)}},

    # ===== C. 形状特型（9 个）=====
    {"name": "某人的头号歌迷", "desc": "曲库五分之一是同一个人",
     "targets": {"artist.top1_share": (0.20, 1.0, 2.0)}},
    {"name": "一柜子同款", "desc": "整柜都是一个流派，闭眼拿都是那个味",
     "targets": {"_derived.top_genre_share": (0.70, 1.0, 2.0)}},
    {"name": "华语钉子户", "desc": "英文歌？先放着",
     "targets": {"region.mandarin_share": (0.90, 1.0, 2.0)}},
    {"name": "跨洋听众", "desc": "中文英文日文韩文，换着来",
     "targets": {"region.non_mandarin_share": (0.40, 1.0, 2.0)}},
    {"name": "黑胶收藏家", "desc": "曲库大、还什么都收",
     "targets": {"scope.tracks": (300.0, 100000.0, 1.5),
                 "coverage.genre_ratio": (0.50, 1.0, 1.0)}},
    {"name": "全自动点唱机", "desc": "什么都点过一遍",
     "targets": {"diversity.genre_entropy": (0.75, 1.0, 1.5),
                 "diversity.artists_per_100_tracks": (30.0, 1000.0, 1.0)}},  # TBD 阈值
    {"name": "雨天限定", "desc": "听的大多是低能量抒情——推断的，不是实测",
     "targets": {"mood.arousal_mean": (*A_LOW, 1.5),
                 "mood.valence_inferred_mean": (0.0, 0.45, 1.0)}},  # TBD 阈值
    {"name": "过山车乘客", "desc": "一会儿安静的，一会儿炸的",
     "targets": {"_derived.arousal_spread": (0.35, 1.0, 2.0)}},  # TBD 阈值
    {"name": "隐藏款听众", "desc": "冷门艺人比例高，热榜上一个找不着",
     "targets": {"diversity.singleton_artist_share": (0.75, 1.0, 2.0)}},  # TBD 阈值
]

# 兜底型不在 TYPES 里 —— 它没有 targets，是「什么都不像」时的答案
WILDCARD = {"name": "薛定谔的听众",
            "desc": "什么都不极端，不好归类——这本身就是一种类型"}
WILDCARD_THRESHOLD = 0.35   # top1 低于它 → 兜底型上第一位


def _augment(facts: dict) -> dict:
    """派生键。

    `genre.album.<流派名>.share` 是动态键（名字随数据变），没法写死在 targets 里；
    过山车的「能量落差」是 max-min，也没有现成键。都在这算一次。
    """
    out = dict(facts)

    top_genre = 0.0
    for k, v in facts.items():
        if k.startswith("genre.album.") and k.endswith(".share"):
            top_genre = max(top_genre, float(v or 0))
    out["_derived.top_genre_share"] = top_genre

    hi = facts.get("mood.arousal_measured_max")
    lo = facts.get("mood.arousal_measured_min")
    if hi is not None and lo is not None:
        out["_derived.arousal_spread"] = float(hi) - float(lo)

    return out


def _target_score(value: float, lo: float, hi: float) -> float:
    """区间内 1.0；界外按到界的距离、以区间宽度为尺度线性衰减到 0。"""
    span = max(hi - lo, 1e-6)
    if value < lo:
        return max(0.0, 1.0 - (lo - value) / span)
    if value > hi:
        return max(0.0, 1.0 - (value - hi) / span)
    return 1.0


def _score_type(t: dict, facts: dict) -> tuple[float, int]:
    """返回 (加权分, 命中的目标数)。

    【为什么要返回命中数】破平局用：两个型都打满分时，**证据更多的那个更像** ——
    「隔壁的 DJ」（能量 + 宽度两条都命中）应该压过「全自动点唱机」
    （只命中了宽度那一条，artists_per_100 缺失时更是只有一条）。
    按名字破平局是任意的，实测会把主组合型挤下去（test 里踩过）。
    """
    num = den = 0.0
    matched = 0
    for key, (lo, hi, w) in t["targets"].items():
        v = facts.get(key)
        if v is None:
            continue                      # 缺数据：跳过，权重重新归一
        matched += 1
        num += w * _target_score(float(v), lo, hi)
        den += w
    return ((num / den) if den else 0.0), matched


def score_types(facts: dict, top: int = 3) -> list[dict]:
    """算 top-N 候选。**确定性**：同 facts 同结果（单测钉住）。"""
    f = _augment(facts)
    order = {t["name"]: i for i, t in enumerate(TYPES)}   # 定义顺序：主组合在前

    scored = []
    for t in TYPES:
        s, matched = _score_type(t, f)
        scored.append({"name": t["name"], "desc": t["desc"],
                       "score": round(s, 4), "matched": matched})

    # 排序：分 → 命中数（证据多的更像）→ 定义顺序（最后的兜底，不再是名字）
    scored.sort(key=lambda x: (-x["score"], -x["matched"], order[x["name"]]))
    out = [{k: v for k, v in x.items() if k != "matched"}   # matched 是内部排序用，不出仓
           for x in scored[:top]]

    # 什么都不像 → 兜底型插到第一位（它的 desc 就是「不好归类」）
    if out and out[0]["score"] < WILDCARD_THRESHOLD:
        rest = [x for x in out if x["name"] != WILDCARD["name"]]
        out = [{"score": 0.0, **WILDCARD}] + rest[: top - 1]

    return out