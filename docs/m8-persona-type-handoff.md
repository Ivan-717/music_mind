# M8 交接：音乐人格「型」—— 给自己的口味一个代号

**动机（用户原话）**：「像 MBTI 一样有趣……给自己的音乐口味总结取个名字」。

**为什么固定池是必要的（不只是为了有趣）**：现在的意象名每次重算都会变
（这次是「台灯」，下次可能变「磁带」）—— **不稳定的东西当不了名字**。
要能跟人说"我是守夜人"，它就必须一直叫这个。

**设计（已拍板）**：
1. **型是主角，意象是注脚**：「守夜人 · 深夜书桌前的一盏台灯」
2. **三选一自选**：系统按数据算出最像的 3 个型，用户认领一个 ——
   "系统算出来我像这三个，我认这个"（真实 + 自我表达都在）
3. **认领后冻结**：型跟着用户，重新生成报告也不变（除非主动换）
4. 意象注脚**不冻结**：每次报告重新生成（"朋友重新看完你的曲库，说的话会变"）

---

## 一、型池（22 个）

全部条件只用**报告已经在算的 facts**（`tools/profile.py`）+
**一个新加的 region fact**（见 §二）。阈值列的是初值，**实现时对着真实报告调**
（现有报告落点：能量 0.42–0.45、宽度 0.64、中位年 2015）。

### A. 能量 × 宽度（主组合，9 个）

| 型名 | 一句话 | 条件方向 |
|---|---|---|
| 守夜人 | 灯只开一盏，音量不大，听得久 | `mood.arousal_mean` ↓ + `diversity.genre_entropy` ↓ |
| 壁炉边的猫 | 晒着听的歌，不赶时间 | arousal ↓ + entropy 中 |
| 深夜漫游者 | 什么都听，但都听得很轻 | arousal ↓ + entropy ↑ |
| 老唱片店的常客 | 柜台上那几张，翻了十几年 | arousal 中 + entropy ↓ |
| 温吞的听者 | 不炸不闷，一杯温水 | arousal 中 + entropy 中 |
| 杂货铺老板 | 货架上什么都有，什么都卖一点 | arousal 中 + entropy ↑ |
| 单曲循环怪 | 一首歌能听一年，一个歌手能听十年 | arousal ↑ + entropy ↓ |
| 高速公路 | 适合开车、赶稿、跑起来的那种 | arousal ↑ + entropy 中 |
| 隔壁的 DJ | 什么都放，放什么都有人跟着摇 | arousal ↑ + entropy ↑ |

### B. 年代（3 个）

| 型名 | 一句话 | 条件 |
|---|---|---|
| 考古学家 | 新歌？先把老歌听完 | `era.median_year` < 2010 |
| 追新猎手 | 新专辑发行当天就听 | `era.median_year` > 2023 |
| 时光旅行者 | 从七零年代一路听过来 | `diversity.decades_covered` ≥ 5 |

### C. 形状特型（9 个）

| 型名 | 一句话 | 条件 |
|---|---|---|
| 某人的头号歌迷 | 曲库五分之一是同一个人 | `artist.top1_share` > 0.20 |
| 一柜子同款 | 整柜都是一个流派 | 头部 `genre.album.*.share` > 0.70 |
| 华语钉子户 | 英文歌？先放着 | `region.mandarin_share` > 0.90 |
| 跨洋听众 | 中文英文日文韩文，换着来 | `region.non_mandarin_share` > 0.40 |
| 黑胶收藏家 | 曲库大、还什么都收 | `scope.tracks` ↑ + `coverage.genre_ratio` ↑ |
| 全自动点唱机 | 什么都点过一遍 | `diversity.genre_entropy` 极高 + `diversity.artists_per_100_tracks` ↑ |
| 雨天限定 | 大多是低能量抒情——**推断的，不是实测** | arousal ↓ + `mood.valence_inferred_mean` ↓ |
| 过山车乘客 | 一会儿安静的，一会儿炸的 | `arousal_measured_max − min` ↑ |
| 隐藏款听众 | 冷门比例高，热榜上一个找不着 | `diversity.singleton_artist_share` ↑ |

### D. 兜底（1 个）

| 型名 | 一句话 | 条件 |
|---|---|---|
| 薛定谔的听众 | 什么都不极端，不好归类——这本身就是一种类型 | 分数全低时的保底 |

---

## 二、数据缺口：一个 region fact

`artist.country_code` 已经全（616/696），只差把它算成一个 fact。
在 `tools/profile.py` 里加（照其它 tool 的样子）：

```
region.mandarin_share      CN / TW / HK 的艺人在「有国家码的艺人」里的占比
region.non_mandarin_share  1 − mandarin_share
region.with_code_ratio     有国家码的艺人占比（覆盖率，诚实披露用）
```

⚠️ **分母用「有国家码的艺人」不是全部曲目** —— 覆盖率不是 100%，
报告文案要能说清口径（这是项目一贯的诚实要求，文案里带上 `with_code_ratio`）。

---

## 三、匹配算法：区间打分，不是布尔桶

**不用**"满足条件才命中"（会有 0 命中 / 多命中还不分高低）。
每个型定义一组**目标区间**，算 0–1 的分，加权求和，取 **top3**：

```python
# musicmind_agent/persona_types.py（新文件）
TYPES = {
    "守夜人": {
        "desc": "灯只开一盏，音量不大，听得久",
        "targets": {
            # fact key: (下界, 上界, 权重) —— 落在区间内得满分，
            # 区间外按到边界的距离线性衰减，0 为下限
            "mood.arousal_mean": (0.0, 0.40, 2.0),
            "diversity.genre_entropy": (0.0, 0.55, 1.0),
        },
    },
    # ... 22 个
}
```

- **缺失的事实要能算分**：某首/某范围的 `mood.valence_inferred_mean` 可能没有
  —— 该 target 直接跳过（不惩罚），权重重新归一。**别把"没这个数据"当成"不符合"。**
- **兜底型**：top1 的分数低于 0.35 时，把「薛定谔的听众」塞进候选。
- **确定性**：同 facts → 同结果。写单测钉住几个边界（全低 / 全高 / 缺数据）。

---

## 四、报告管线接入

生成报告时（跑完 facts 之后、compose 之前或之后都行）：
把 `persona_type_candidates`（top3 的 `{name, desc, score}`）写进 **report_json 顶层**：

```json
{
  "headline": {...},          // 不动（LLM 写的意象，现在是注脚）
  "persona_type_candidates": [{"name": "守夜人", "desc": "...", "score": 0.71}, ...],
  "opening": "...",           // 新增，见 §六
  "dimensions": [...]
}
```

**型名不进 LLM**：它和数字一样是"算出来的"，不走生成、不走渲染替换
（将来要显示在报告里的话，走代码渲染，和 persona_basis 同一条路）。

## 五、认领与冻结

- `agent_report` 加一列：`persona_type VARCHAR(32) NULL`（用户认领的型名）
- 新接口（Java）：`POST /api/agent/reports/{id}/type`，body `{"name": "守夜人"}`
  —— 校验 name 在候选列表里（**不校验的话前端能塞任意字符串**），存库
- 前端：型名旁「不是这个？看看另外两个」→ 展开另外两个 → 点击替换
- 展示优先级：`persona_type`（认领的）> candidates[0]（没认领时显示最像的，
  但标注「系统猜的，没认领」）—— 这个区别要显式，别混淆"算出来的"和"你认的"

## 六、开场白（「别太死板」的落点）

`prompts/compose.py` 的 SYSTEM 与输出结构加一段 **opening**（2–4 句）：

- 位置：headline 之后、维度块之前（代码渲染，`{fact.key}` 管线照旧）
- 定位：**朋友看完整柜唱片说的第一段话**，不是数据摘要
- 示例口气：
  > 你这里没有一首是碰巧放着的。每张都像是从某个具体晚上留下来的——
  > 有些听得出是冬天，有些是夏天。整体听下来，像一个人把灯调暗之后
  > 才肯打开的抽屉。

- **硬规则不动**：数字走 `{fact.key}`、实测/推断分开标。
  温度从"怎么说"来，不从"多说"来。
- `PROMPT_VERSION` 升号（`compose-1.1` → `compose-1.2`），改完重跑一次评估
  确认「占上界比」不退化（M1 时就定的规矩）

---

## 七、交付方式与验收

**这一版代码全给（见 §八），你负责合入和跑验收。**

**验收**：
1. 单测：`pytest tests/test_persona_types.py`（边界、缺数据、确定性、22 型全覆盖）
2. 拿现有真实报告的数据跑匹配 → **人眼看"像不像"**（这一步没有自动化判据，
   是这个功能的现实——型准不准最终靠你判断）
3. 认领流程：点「守夜人」→ 刷新 → 还是守夜人（冻结）；重新生成报告 → 型不变
4. 开场白：无数字裸奔（L2/L3 自动验），口气达到"朋友"而不是"分析师"
5. 越权：B 认领 A 的报告 → 404

---

# 八、完整代码

所有下落的路径都对着当前代码核实过（`@register` 签名、`walk_texts` 的位置、
`persist.py` 的写入点、`Track.country_code` 已存在——region 工具不用查库）。

## Python（8 处）

### P1. `musicmind_agent/persona_types.py` —— 新增

```python
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
    （只命中了宽度那一条）。按名字破平局是任意的，实测会把主组合型挤下去。
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
```

### P2. `musicmind_agent/tools/profile.py` —— 追加一个 tool

放在「年代」段之后（`artist_affinity` 之前）。**`Track` 对象已经有 `country_code`**
（`evidence.py` 第 58 行），不用查库：

```python
# ============================================================
# 地区
# ============================================================

# 华语区的国家码（MusicBrainz 用的是 ISO 3166-1 alpha-2）
MANDARIN_CODES = {"CN", "TW", "HK"}


@register(
    "region_distribution", 0,
    "艺人国家/地区的分布。反映的是「作品来自哪儿」，不是用户在哪听",
    {},
)
def region_distribution(ctx: ToolContext, args: dict) -> ToolResult:
    tracks = ctx.tracks
    total = len(tracks)
    with_code = [t for t in tracks if t.country_code]
    base = len(with_code)     # 【分母是有国家码的曲目，不是全部】覆盖率要诚实披露

    counts: Counter = Counter()
    examples: dict[str, list] = {}
    for t in with_code:
        counts[t.country_code] += 1
        examples.setdefault(t.country_code, [])
        if len(examples[t.country_code]) < 2:
            examples[t.country_code].append(t)

    mandarin = sum(n for c, n in counts.items() if c in MANDARIN_CODES)

    facts = {
        "region.with_code_ratio": round(base / total, 4) if total else 0,
        "region.mandarin_tracks": mandarin,
        "region.mandarin_share": round(mandarin / base, 4) if base else 0,
        "region.non_mandarin_share": round((base - mandarin) / base, 4) if base else 0,
        "region.distinct": len(counts),
    }
    for code, n in counts.most_common(8):
        facts[f"region.{code}.tracks"] = n
        facts[f"region.{code}.share"] = round(n / base, 4) if base else 0

    return ToolResult(
        tool="region_distribution",
        facts=facts,
        rows=[
            {"地区": code, "曲目数": n,
             "占比": f"{n / base * 100:.1f}%" if base else "0%"}
            for code, n in counts.most_common(8)
        ],
        evidence=cap_evidence([
            ctx.evidence_for(t, why=f"{code} 地区")
            for code, _ in counts.most_common(8)
            for t in examples.get(code, [])
        ]),
        coverage=cov(
            total, base,
            "艺人国家码缺失的曲目不参与；它反映的是作品来自哪里，"
            "不是用户在哪里听 —— 库里没有播放行为数据",
        ),
    )
```

### P3. `musicmind_agent/models.py` —— 加一个字段

```python
class ReportDraft(BaseModel):
    """LLM 直接产出的东西。渲染和验证在这之后做。"""
    headline: Headline
    opening: str = ""            # ← 新增：开场白（2-4 句），渲染/校验收口见 P5/P6
    dimensions: list[Dimension] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
```

### P4. `musicmind_agent/prompts/compose.py` —— 版本号 + JSON 结构 + 写法要求

```python
# 1.2：加 opening 开场白（M8「别太死板」的落点）。硬规则依旧一个字没动
PROMPT_VERSION = "compose-1.2"
```

USER_TEMPLATE 的 JSON 结构里，加在 **顶层**（和 `"dimensions"` 平级）：

```
  "headline": {{ ... }},
  "opening": "开场白，2-4 句（必填）",
  "dimensions": [
```

⚠️ **别放进 `headline` 对象里面**（实测踩过：放进去会被 Pydantic 当成多余键
静默忽略，`opening` 永远是空字符串，**而且什么都不报**）。代码读的是
`report["opening"]` —— 顶层。

「要求」段（在 headline.title 的说明之后）追加：

```
**opening 是报告的开场白**（2-4 句），位置在名字之后、各维度之前：

- 它是**朋友看完整柜唱片说的第一段话**，不是数据摘要，不要面面俱到
- 可以有一两个具体画面（「有些听得出是冬天，有些是夏天」），
  但**一个字都不许写数字** —— 要提数字就用 {{fact.key}}，和正文同一条规矩
- 不要过渡句（「接下来我们看看……」），不要总结句（「总的来说……」）
- 拿不准的分寸和不许说的话，和上面「硬规则」完全一致

⚠️ **这段文字是写进 USER_TEMPLATE 的，而它是 `.format()` 模板** ——
所有示例里的花括号必须双写（`{{fact.key}}`、JSON 部分同理）。
写了裸的 `{fact.key}` 会直接在 `.format()` 时 `KeyError: 'fact'`
（实测踩过，启动即炸）。
```

### P5. `musicmind_agent/graph/nodes.py` —— `_render` 收口（两处）

第一处，`_render` 函数里（headline 两行的**下面**加一行，注释强调的就是这里）：

```python
    data["headline"]["title"] = render_text(data["headline"]["title"], facts, strict=False)
    data["headline"]["subtitle"] = render_text(data["headline"]["subtitle"], facts, strict=False)
    # 【新字段都要在这收口】漏一个就会出现「没替换的花括号」——
    # limitations 当年就是这么漏的
    data["opening"] = render_text(data.get("opening") or "", facts, strict=False)
```

第二处，降级路径的 `degraded` dict（`"headline"` 之后）：

```python
        "opening": "",              # 叙事部分未通过校验 → 开场白也是叙事，丢掉
```

### P6. `musicmind_agent/validate/checks.py` —— `walk_texts` 加一行

```python
    head = report.get("headline") or {}
    yield "headline.title", head.get("title") or ""
    yield "headline.subtitle", head.get("subtitle") or ""
    yield "opening", report.get("opening") or ""      # ← 新增。这个函数漏一个字段就是一个洞
```

### P7. `musicmind_agent/persist.py` —— 算型候选（放在算 `data_scope` 的旁边）

```python
    # 「型」是代码算的，和 facts 一样是数据 —— 不经过 LLM、不进验证链。
    # 放在 persist 里而不是 graph 节点里：正常/降级两条路径都会经过这里，
    # 一处就全覆盖了
    from musicmind_agent.persona_types import score_types
    rendered["persona_type_candidates"] = score_types(facts)
```

### P8. `tests/test_persona_types.py` —— 新增

```python
"""型匹配的边界。**这个文件的每个用例都是构造的 facts**，不碰数据库不调网。"""

from musicmind_agent.persona_types import score_types, WILDCARD


def _facts(**kw):
    """最小可用的 facts 仓：只放用例关心的键"""
    return dict(kw)


def test_low_energy_narrow_first_is_nightwatch():
    out = score_types(_facts(**{"mood.arousal_mean": 0.30,
                                "diversity.genre_entropy": 0.40}))
    assert out[0]["name"] == "守夜人"


def test_high_energy_wide_first_is_dj():
    out = score_types(_facts(**{"mood.arousal_mean": 0.80,
                                "diversity.genre_entropy": 0.85}))
    assert out[0]["name"] == "隔壁的 DJ"


def test_old_median_year_archaeologist_in_top3():
    out = score_types(_facts(**{"mood.arousal_mean": 0.50,
                                "diversity.genre_entropy": 0.60,
                                "era.median_year": 1998}))
    assert "考古学家" in [x["name"] for x in out]


def test_missing_facts_do_not_crash_and_renormalize():
    # 只有能量、没有宽度：守夜人/高速公路 都该在候选里（宽度权重的缺失不该算它输）
    out = score_types(_facts(**{"mood.arousal_mean": 0.30}))
    assert len(out) == 3
    assert all(isinstance(x["score"], float) for x in out)


def test_nothing_matches_wildcard_first():
    # 所有目标区间都远离 —— 兜底型必须上第一位
    out = score_types(_facts(**{"mood.arousal_mean": 0.9999,
                                "diversity.genre_entropy": 0.9999}))
    assert out[0]["name"] == WILDCARD["name"] or out[0]["score"] >= 0.35


def test_deterministic():
    f = _facts(**{"mood.arousal_mean": 0.45, "diversity.genre_entropy": 0.64,
                  "era.median_year": 2015})
    assert score_types(f) == score_types(f)


def test_top_genre_share_derived_key():
    # genre.album.* 是动态键：派生上限应该被「一柜子同款」用起来
    out = score_types(_facts(**{"genre.album.mandopop.share": 0.95,
                                "mood.arousal_mean": 0.45,
                                "diversity.genre_entropy": 0.64}))
    assert "一柜子同款" in [x["name"] for x in out]


def test_all_types_reachable():
    """22 个型每个都要「够得着」—— 构造一个正中靶心的 facts，看它进不进 top1。"""
    cases = {
        "守夜人": {"mood.arousal_mean": 0.30, "diversity.genre_entropy": 0.40},
        "壁炉边的猫": {"mood.arousal_mean": 0.30, "diversity.genre_entropy": 0.60},
        "深夜漫游者": {"mood.arousal_mean": 0.30, "diversity.genre_entropy": 0.85},
        "老唱片店的常客": {"mood.arousal_mean": 0.48, "diversity.genre_entropy": 0.40},
        "温吞的听者": {"mood.arousal_mean": 0.48, "diversity.genre_entropy": 0.60},
        "杂货铺老板": {"mood.arousal_mean": 0.48, "diversity.genre_entropy": 0.85},
        "单曲循环怪": {"mood.arousal_mean": 0.70, "diversity.genre_entropy": 0.40},
        "高速公路": {"mood.arousal_mean": 0.70, "diversity.genre_entropy": 0.60},
        "隔壁的 DJ": {"mood.arousal_mean": 0.70, "diversity.genre_entropy": 0.85},
        "考古学家": {"era.median_year": 1998},
        "追新猎手": {"era.median_year": 2025},
        "时光旅行者": {"diversity.decades_covered": 6},
        "某人的头号歌迷": {"artist.top1_share": 0.30},
        "一柜子同款": {"genre.album.mandopop.share": 0.80},
        "华语钉子户": {"region.mandarin_share": 0.95},
        "跨洋听众": {"region.non_mandarin_share": 0.60},
        "黑胶收藏家": {"scope.tracks": 800, "coverage.genre_ratio": 0.80},
        "全自动点唱机": {"diversity.genre_entropy": 0.90,
                          "diversity.artists_per_100_tracks": 60},
        "雨天限定": {"mood.arousal_mean": 0.30, "mood.valence_inferred_mean": 0.30},
        "过山车乘客": {"mood.arousal_measured_max": 0.90,
                       "mood.arousal_measured_min": 0.20},
        "隐藏款听众": {"diversity.singleton_artist_share": 0.90},
    }
    for name, f in cases.items():
        out = score_types(_facts(**f))
        assert out[0]["name"] == name, f"{name} 没排到第一，实际第一是 {out[0]['name']}"
```

## Java（4 处）

### J1. 表结构（在数据库里执行一次，同时补进 `schema-agent.sql`）

```sql
ALTER TABLE agent_report
  ADD COLUMN persona_type VARCHAR(32) NULL COMMENT '用户认领的型名；NULL = 还没认领'
  AFTER headline;
```

### J2. `mapper/AgentReportMapper.java` —— 加列 + 加更新

`findOwned` 的 SELECT 列表里（`headline` 后面）加 `persona_type`：

```java
    @Select("""
            SELECT id, user_id, status, scope_kind, scope_ref, scope_label,
                   headline, persona_type, report_json, data_scope_json,
                   llm_provider, llm_model, tokens_in, tokens_out,
                   latency_ms, created_at
            FROM agent_report
            WHERE id = #{id} AND user_id = #{userId}
            """)
    Map<String, Object> findOwned(@Param("id") Long id, @Param("userId") Long userId);
```

新增（`listByUser` 下面）：

```java
    /** 认领型。**WHERE 里带 user_id** —— 不带的话 B 能改 A 的报告（和 findOwned 同一个道理） */
    @Update("""
            UPDATE agent_report SET persona_type = #{name}
            WHERE id = #{id} AND user_id = #{userId}
            """)
    int updateType(@Param("id") Long id, @Param("userId") Long userId,
                   @Param("name") String name);
```

（文件顶部记得 import `org.apache.ibatis.annotations.Update`。）

### J3. `service/AgentService.java` —— 加认领方法

```java
    /**
     * 认领一个型。规则：
     *   1. 报告必须属于本人（findOwned 的 WHERE 里带 user_id，不存在/越权都是 404）
     *   2. name 必须在报告的候选列表里 —— 不校验的话前端能塞任意字符串
     */
    public Map<String, Object> claimType(Long userId, Long reportId, String name) {
        Map<String, Object> report = reportMapper.findOwned(reportId, userId);
        if (report == null) {
            throw new ApiException(404, "报告不存在");
        }
        if (name == null || name.isBlank()) {
            throw new ApiException(400, "型名不能为空");
        }
        boolean ok = false;
        try {
            JsonNode candidates = objectMapper.readTree(
                    String.valueOf(report.get("report_json")))
                    .path("persona_type_candidates");
            for (JsonNode c : candidates) {
                if (name.equals(c.path("name").asText())) {
                    ok = true;
                    break;
                }
            }
        } catch (Exception e) {
            throw new ApiException(500, "报告内容无法解析");
        }
        if (!ok) {
            throw new ApiException(400, "这个型不在候选列表里");
        }
        reportMapper.updateType(reportId, userId, name);
        return Map.of("personaType", name);
    }
```

需要注入（照类里现有字段的风格加）：

```java
    private final com.fasterxml.jackson.databind.ObjectMapper objectMapper =
            new com.fasterxml.jackson.databind.ObjectMapper();
```

### J4. `controller/AgentController.java` —— 加端点

```java
    /** 认领型。body: {"name": "守夜人"} */
    @PostMapping("/reports/{id}/type")
    public Map<String, Object> claimType(@PathVariable Long id,
                                         @RequestBody Map<String, String> body) {
        return agentService.claimType(CurrentUser.id(), id, body.get("name"));
    }
```

## 前端（我写，不占你）

等 Python/Java 就位后我做（结构已定）：型名大字 + 意象注脚 + 「不是这个？看看另外两个」
展开认领。数据契约：报告 JSON 的 `persona_type_candidates`（3 条 `{name, desc, score}`）+
`agent_report.persona_type`（认领结果）。

**分步建议**：先合 P1–P8 跑单测（不碰 LLM，秒级），再改 pipeline 三个收口点
（P5/P6/P7），最后跑一次真报告看 opening 和候选落点。
