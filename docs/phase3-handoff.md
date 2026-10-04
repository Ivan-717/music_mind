# Phase 3 交接：幻觉防治（验证器五层）

**这一步是你写，我验收。** 目标：把「报告里的每个数字、每个实体、每条证据都能被
机械核对」变成代码，而且**零 LLM 参与** —— 验证器一旦调用 LLM，它的结论就同样
需要被验证，防线就退化成递归。

```bash
.venv/Scripts/python.exe -m musicmind_agent.cli validate --report out/report-34.json --user 34
```

---

## 起点：为什么需要它

Phase 2 跑出来的两份报告，实测抓到了这些真实的错：

| 现象 | 谁犯的 | 属于哪一层 |
|---|---|---|
| 写了 `mood.arousal_measured_median` —— 这个事实**不存在**，是它把 `arousal_measured_mean/min/max` 和 `arousal_median` 两个名字拼出来的 | qwen | L1 结构 |
| 34 条证据、5 个锚点全部用了**推荐候选**的 id（不是用户的歌） | deepseek 第一版 | L5 证据 |
| 推荐理由写「共享相似的都市疏离感」—— 这是**推断冒充事实**，`matched_dimensions` 里没有任何一条能证实它 | qwen | L5 证据 |
| 把 `coverage.genre_ratio`（89.5%，任一来源）当成专辑级覆盖率（实际 31%），写出自相矛盾的句子 | deepseek 第一版 | L2 引用 |

这四个都不是假设出来的，是**真实跑出来的失败样本**。验证器的验收标准就是能把它们全抓住。

---

## 一个已经存在的粗版

我之前为了给你验收，写了 `agent-service/verify_report.py`。它已经做了 L1 和 L5 的
粗糙版本（扫未渲染占位符、查 id 越界）。

**Phase 3 就是把它变成结构化的、可测的、分层的、能进流程的东西。** 你可以先读它，
但不要在上面打补丁 —— 它是一次性脚本，没有类型、没有分层、混着数据库连接。

---

## 五层，从便宜到贵

```
L1 结构层    不解析的占位符、空口断言          ← 一个字都不用查库
L2 引用层    metric_ref 的 expect 和实际值对不上
L3 字面量层  叙事里的裸数字绑不到任何事实       ← 要扫全文、要归一化中文数字
L4 实体层    提到的艺人/专辑/流派名不在本轮数据里 ← 要建名称索引
L5 证据回查  证据/锚点越界、声称的属性查不实     ← 最强，要回查数据库
```

**为什么这个顺序**：越前面越便宜、越确定。L1 抓到的错不值得再往下走；
L5 最强但最慢，而且只有前面的层没话说时它的结论才可信。

---

## 要建的文件（4 个）

```
agent-service/
  musicmind_agent/
    validate/
      __init__.py     ← 1. 入口 + 数据类型
      normalize.py    ← 2. 数字与名称的归一化（L3/L4 的公共件）
      checks.py       ← 3. 五层检查
  tests/
    test_validate.py  ← 4. 用真实失败样本做回归
  musicmind_agent/cli.py  ← 5. 加 validate 子命令
```

---

## 1. `musicmind_agent/validate/__init__.py`

```python
"""报告验证：五层确定性检查，零 LLM。

【为什么必须零 LLM】用 LLM 去验证 LLM，它的结论同样需要被验证 ——
防线退化成递归，而且你永远不知道哪一层的判断是可信的。
这里的每一条都是可以单测的纯逻辑。

【为什么是五层而不是一个大函数】每层的成本差一个数量级：
L1 只要一个正则，L5 要回查数据库。分层的意义是「便宜的足以定案时就不跑贵的」，
以及出错时能立刻说出是哪一类问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from musicmind_agent.tools import ToolContext

# 严重程度
#   error   报告不允许落库。Phase 4 会打回重写，重试失败则降级渲染
#   warning 记下来，但不阻断。通常是「可能有问题但无法机械判定」
ERROR = "error"
WARNING = "warning"


@dataclass
class Violation:
    layer: str        # structure / reference / literal / entity / evidence
    path: str         # 报告里的位置，如 dimensions[0].claims[1].text
    detail: str
    severity: str = ERROR


@dataclass
class ValidationResult:
    violations: list[Violation] = field(default_factory=list)
    checked: int = 0        # 检查了多少个断言（分母，让「0 违规」有意义）

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == ERROR]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return f"通过（检查了 {self.checked} 处）"
        parts = [f"检查 {self.checked} 处"]
        if self.errors:
            parts.append(f"违规 {len(self.errors)}")
        if self.warnings:
            parts.append(f"警告 {len(self.warnings)}")
        return "，".join(parts) + "\n" + "\n".join(
            f"  [{v.layer}] {v.path}: {v.detail}" for v in self.violations
        )


def validate(
    report: dict,
    ctx: ToolContext,
    candidate_ids: set[int] | None = None,
) -> ValidationResult:
    """跑全部五层。

    report        —— 渲染之后的报告 dict（数字已经替换成真值）
    ctx           —— 工具上下文：facts / 用户的曲目 / 连接
    candidate_ids —— 推荐候选的 id 池。传 None 就跳过「推荐是否来自候选池」这一项
    """
    from musicmind_agent.validate import checks

    result = ValidationResult()
    for layer_fn in (
        checks.check_structure,
        checks.check_references,
        checks.check_literals,
        checks.check_entities,
        checks.check_evidence,
    ):
        layer_fn(report, ctx, result, candidate_ids)
    return result


__all__ = ["Violation", "ValidationResult", "validate", "ERROR", "WARNING"]
```

---

## 2. `musicmind_agent/validate/normalize.py`

```python
"""数字和名称的归一化。L3 / L4 的公共件。

【为什么要单独一个文件】「能不能绑到某条事实」这个判断在两个层里都要用，
而且它比看起来难：中文数字、百分比和小数、四舍五入、带千分位。
写两遍一定漂移，而漂移的表现是「同一个数字在一层能过、另一层过不了」。
"""

from __future__ import annotations

import re

from zhconv import convert

# 中文数字。只覆盖报告里实际会出现的量级 —— 没人会在乐评里写「三万两千首」
CN_DIGITS = {
    "零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 「三成」「两首」「近一半」「三分之一」这类
CN_APPROX = {
    "一半": 0.5, "半": 0.5, "三分之一": 1 / 3, "四分之一": 0.25,
    "三成": 0.3, "四成": 0.4, "五成": 0.5, "六成": 0.6,
    "七成": 0.7, "八成": 0.8, "九成": 0.9,
}


def parse_cn_number(text: str) -> float | None:
    """把「三」「十」「十二」「二十」这类解析成数字。解析不了返回 None。"""
    if text in CN_APPROX:
        return CN_APPROX[text]
    if not text:
        return None
    if text == "十":
        return 10.0
    if text.endswith("十"):
        head = CN_DIGITS.get(text[:-1])
        return head * 10.0 if head is not None else None
    if "十" in text:
        head, tail = text.split("十", 1)
        h = CN_DIGITS.get(head) if head else 1
        t = CN_DIGITS.get(tail)
        if h is None or t is None:
            return None
        return h * 10.0 + t
    if len(text) == 1:
        value = CN_DIGITS.get(text)
        return float(value) if value is not None else None
    return None


def numeric_forms(value: float) -> set[str]:
    """一个数值在文本里可能长什么样。

    「能绑上」不是字符串相等 —— 0.6835 在报告里会写成 68.3%，也可能写成 68%、
    0.68。全部列出来，任何一个命中就算绑上了。
    """
    forms = {
        f"{value:.2f}", f"{value:.1f}", f"{value:.0f}",
        f"{value:.2%}", f"{value:.1%}", f"{value:.0%}",
        f"{value * 100:.2f}", f"{value * 100:.1f}", f"{value * 100:.0f}",
        f"{int(value)}" if value == int(value) else "",
    }
    return {f for f in forms if f}


NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?%?")


def extract_numbers(text: str) -> list[str]:
    return NUMBER_RE.findall(text or "")


def canonical(value: float, places: int = 2) -> str:
    return f"{round(value, places):.2f}"


def name_variants(text: str) -> set[str]:
    """繁简 + 空格 + 大小写归一。**这个仓库里凡是比名字的地方都要用它** ——
    已经在实体对齐和 iTunes 匹配上栽过两次，别再栽第三次。"""
    if not text:
        return set()
    base = text.replace(" ", "").lower()
    out = {base, convert(base, "zh-cn").replace(" ", "").lower(),
           convert(base, "zh-tw").replace(" ", "").lower()}
    return {o for o in out if o}


def name_matches(needle: str, haystack: str) -> bool:
    """needle 的任一繁简变体出现在 haystack 的任一变体里。两边都要展开。"""
    return any(n in h for n in name_variants(needle) for h in name_variants(haystack))
```

---

## 3. `musicmind_agent/validate/checks.py`

```python
"""五层检查。每一层都往 result 里追加违规，不抛异常。

【为什么不抛】一次跑完收集所有问题，才能一次把完整的错误清单回灌给模型修。
一次只报一个错会让重写轮次爆炸（每次修一个，改完又冒一个）。
"""

from __future__ import annotations

import json
import re

from musicmind_agent.evidence import load_enriched
from musicmind_agent.render import PLACEHOLDER
from musicmind_agent.tools import ToolContext
from musicmind_agent.validate import ERROR, WARNING, ValidationResult
from musicmind_agent.validate.normalize import (
    canonical,
    extract_numbers,
    name_matches,
    name_variants,
    numeric_forms,
    parse_cn_number,
)

CN_NUMBER_RE = re.compile(
    r"(?<![\d.])([零一二两三四五六七八九十]+|一半|三分之一|四分之一|"
    r"[三四五六七八九]成|\d+(?:\.\d+)?%?)(?![\d.])"
)


# ============================================================
# 遍历报告的工具
# ============================================================

def walk_claims(report: dict):
    """产出 (路径, claim dict)。所有 claim 级的检查共用。"""
    for i, dim in enumerate(report.get("dimensions") or []):
        for j, claim in enumerate(dim.get("claims") or []):
            yield f"dimensions[{i}].claims[{j}]", claim


def walk_texts(report: dict):
    """产出 (路径, 文本)。所有文本级的检查共用 ——
    **必须覆盖每一个 LLM 写的字段**，漏一个就是一个洞。
    第一版就是漏了 limitations，于是那里面带着花括号原样输出了。"""
    head = report.get("headline") or {}
    yield "headline.title", head.get("title") or ""
    yield "headline.subtitle", head.get("subtitle") or ""

    for path, claim in walk_claims(report):
        yield f"{path}.text", claim.get("text") or ""

    for i, dim in enumerate(report.get("dimensions") or []):
        yield f"dimensions[{i}].summary", dim.get("summary") or ""

    for i, rec in enumerate(report.get("recommendations") or []):
        yield f"recommendations[{i}].reason", rec.get("reason") or ""
        rel = rec.get("relation_to_history") or {}
        yield f"recommendations[{i}].relation_to_history.note", rel.get("note") or ""

    for i, item in enumerate(report.get("limitations") or []):
        yield f"limitations[{i}]", item or ""


# ============================================================
# L1 结构层
# ============================================================

def check_structure(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """不解析的占位符、空口断言、引用不存在的事实。**一个字都不用查库。**"""

    # --- 未解析的占位符 ---
    # 渲染时 strict=False 会把解析不了的 key 原样留下。留下的原因只有一个：
    # 这个 key 不在 facts 仓里 —— 也就是模型**编了一个事实名**。
    # 实测样本：qwen 写了 mood.arousal_measured_median，
    # 而仓里只有 arousal_measured_mean/min/max 和 arousal_median。
    for path, text in walk_texts(report):
        result.checked += 1
        for match in PLACEHOLDER.finditer(text):
            key = match.group(1)
            result.violations.append(Violation_(
                "structure", path,
                f"引用了不存在的事实 {key!r}"
                + ("（键名看起来像两个真实键的拼接）" if _looks_stitched(key, ctx) else ""),
            ))

    # --- metric_ref 的 key 必须存在 ---
    for path, claim in walk_claims(report):
        for ref in claim.get("metric_refs") or []:
            key = ref.get("key")
            if key and key not in ctx.facts:
                result.violations.append(Violation_(
                    "structure", path, f"metric_ref 指向不存在的事实 {key!r}"))

        # --- 不许空口断言 ---
        # 每条 claim 要么引用了事实（有数字支撑），要么挂了证据（能指回歌），
        # 两者都没有就是「凭感觉说」，而原则 4 要求可解释
        has_ref = bool(claim.get("metric_refs"))
        has_ev = bool(claim.get("evidence_track_ids"))
        result.checked += 1
        if not has_ref and not has_ev:
            result.violations.append(Violation_(
                "structure", path, "这条结论既没有引用事实也没有证据曲目", WARNING))

    # --- 核心维度必须齐全 ---
    # 核心维度固定是设计决定（两次运行才可比）。缺了要报警，但不阻断 ——
    # 模型偶尔漏一个不该让整份报告作废
    present = {d.get("dimension") for d in report.get("dimensions") or []}
    for required in ("genre", "era", "artist", "mood_energy"):
        result.checked += 1
        if required not in present:
            result.violations.append(Violation_(
                "structure", "dimensions", f"缺少核心维度 {required}", WARNING))


def _looks_stitched(key: str, ctx: ToolContext) -> bool:
    """这个不存在的 key 看起来是不是两个真实 key 拼出来的。

    写这条是为了让报错信息有用 —— 「引用了不存在的事实」和
    「你似乎把 A 和 B 拼在了一起」对模型的重写完全是两种提示。
    """
    parts = key.split(".")
    if len(parts) < 3:
        return False
    return any(f"{'.'.join(parts[:i])}.{'.'.join(parts[i:])}" != key
               and '.'.join(parts[:i]) in ctx.facts
               and '.'.join(parts[i:]) in ctx.facts
               for i in range(1, len(parts)))


def Violation_(layer, path, detail, severity=ERROR):
    from musicmind_agent.validate import Violation
    return Violation(layer=layer, path=path, detail=detail, severity=severity)


# ============================================================
# L2 引用层
# ============================================================

def check_references(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """metric_ref 里模型自己声明的 expect 值，和事实仓的实际值对得上吗。

    比「编数字」更隐蔽的一种错：**引用了真实存在的事实名，但读错了值**。
    实测样本：把 coverage.genre_ratio（89.5%，任一来源）当成专辑级的覆盖率
    （实际 31%），写出了自相矛盾的句子。
    """
    for path, claim in walk_claims(report):
        for ref in claim.get("metric_refs") or []:
            key = ref.get("key")
            expect = ref.get("expect")
            if key not in ctx.facts or expect is None:
                continue

            result.checked += 1
            actual = ctx.facts[key]
            tol = ref.get("tol", 0.005)

            if isinstance(actual, (int, float)) and isinstance(expect, (int, float)):
                if abs(float(actual) - float(expect)) > tol:
                    result.violations.append(Violation_(
                        "reference", path,
                        f"{key}：报告声明 {expect}，实际 {actual}（差超过 {tol}）"))
            elif actual != expect:
                result.violations.append(Violation_(
                    "reference", path, f"{key}：报告声明 {expect!r}，实际 {actual!r}"))


# ============================================================
# L3 字面量层
# ============================================================

def check_literals(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """叙事里的裸数字，必须能绑到某条事实、或某首证据曲目的年份/时长。

    为什么需要它：占位符机制堵死了「主动编数字」，但模型可能**忘了用占位符**
    而直接写「68.3%」。这种要被抓到 —— 要么改成引用，要么证明它确实对得上。

    中文数字（「三成」「两首」）也要归一化后一起判 ——
    只扫阿拉伯数字的话，换一种写法就绕过去了。
    """
    # 所有允许出现的数字形态
    allowed: set[str] = set()
    for value in ctx.facts.values():
        if isinstance(value, (int, float)):
            allowed |= numeric_forms(float(value))

    # 证据曲目的年份和时长也是合法数字（「2016 年发行的《xxx》」）
    for track in ctx.tracks:
        if track.year:
            allowed.add(str(track.year))
        if track.duration_ms:
            allowed.add(str(track.duration_ms // 1000))
            allowed.add(f"{track.duration_ms // 60000}:{track.duration_ms // 1000 % 60:02d}")

    for path, text in walk_texts(report):
        cleaned = PLACEHOLDER.sub(" ", text)
        result.checked += 1
        for raw in CN_NUMBER_RE.findall(cleaned):
            token = raw
            if not token[0].isdigit():
                parsed = parse_cn_number(token)
                if parsed is None:
                    continue
                token = canonical(parsed)
            else:
                token = token.rstrip("%")
                if "%" in raw:
                    token = f"{float(token) / 100:.2f}"

            if token in allowed:
                continue
            # 允许四舍五入到整数后命中
            try:
                if f"{float(token):.0f}" in allowed or f"{float(token):.1f}" in allowed:
                    continue
            except ValueError:
                pass
            result.violations.append(Violation_(
                "literal", path, f"数字 {raw!r} 绑不到任何事实或证据", WARNING))


# ============================================================
# L4 实体层
# ============================================================

def check_entities(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """提到的艺人/专辑/流派名，必须能在本轮数据里找到。

    这是「编造了一个不存在的专辑」的**唯一机械防线**。
    名字来自：用户曲目的艺人/专辑/流派 + 本轮所有工具 facts 里的流派名。
    """
    known: list[str] = []
    for track in ctx.tracks:
        if track.artist_name:
            known.append(track.artist_name)
        if track.album_name:
            known.append(track.album_name)
        known.extend(track.genres)

    # facts 里的流派名（genre.album.xxx.tracks 这种 key 里带着流派名）
    for key in ctx.facts:
        parts = key.split(".")
        if len(parts) >= 3 and parts[0] == "genre":
            known.append(parts[-2].replace("_", " "))

    known_variants = [(n, name_variants(n)) for n in known if n]

    # 用「书名号 / 引号」里包裹的专名当候选。比全文本分词可靠得多，
    # 而且模型提到专辑名时几乎总带书名号
    for path, text in walk_texts(report):
        result.checked += 1
        for quoted in re.findall(r"《([^》]+)》", text):
            # 歌名不在 known 里很正常（推荐曲目不在用户库里），所以只当警告
            if not any(any(q in v for v in vars_) for _, vars_ in known_variants
                       for q in name_variants(quoted)):
                result.violations.append(Violation_(
                    "entity", path, f"提到的《{quoted}》不在本轮数据里", WARNING))


# ============================================================
# L5 证据回查层（最强）
# ============================================================

def check_evidence(report, ctx, result: ValidationResult, candidate_ids=None) -> None:
    """证据/锚点越界、声称的属性查不实、推荐了已有的歌。

    这是五层里最强的一层：它不看模型说了什么，而是**回数据库查它说的对不对**。
    """
    user_ids = set(ctx.evidence.all_ids)
    by_id = {t.track_id: t for t in ctx.tracks}

    # --- 证据必须属于用户 ---
    for path, claim in walk_claims(report):
        for tid in claim.get("evidence_track_ids") or []:
            result.checked += 1
            if tid not in user_ids:
                result.violations.append(Violation_(
                    "evidence", path,
                    f"证据曲目 {tid} 不是用户的歌"
                    + ("（它可能是推荐候选 —— 候选不是用户听过的）"
                       if candidate_ids and tid in candidate_ids else "")))

    # --- 推荐项 ---
    rec_ids = [r.get("track_id") for r in report.get("recommendations") or []]
    candidates = {t.track_id: t for t in load_enriched(ctx.connection, [i for i in rec_ids if i])}

    for i, rec in enumerate(report.get("recommendations") or []):
        path = f"recommendations[{i}]"
        tid = rec.get("track_id")
        result.checked += 1

        if tid in user_ids:
            result.violations.append(Violation_(
                "evidence", path, f"推荐了用户已经有的歌 {tid}"))
        if candidate_ids is not None and tid not in candidate_ids:
            result.violations.append(Violation_(
                "evidence", path, f"推荐 {tid} 不在候选池里"))
        if tid not in candidates:
            result.violations.append(Violation_(
                "evidence", path, f"推荐 {tid} 在库里不存在"))
            continue

        # --- 锚点必须属于用户 ---
        for anchor in (rec.get("relation_to_history") or {}).get("anchors") or []:
            result.checked += 1
            if anchor not in user_ids:
                result.violations.append(Violation_(
                    "evidence", path, f"锚点 {anchor} 不是用户的歌"))

        # --- 声称的属性必须查得实 ---
        # 【这一条是原则 4 的机器可校验形式】
        # 说「同为 mandopop」→ 回查候选的流派里真有 mandopop
        # 说「同属低能量」→ 回查 track_audio_feature，**而且必须是实测行** ——
        #   推断出来的能量不能用来支撑这个断言
        target = candidates[tid]
        dims = set(rec.get("matched_dimensions") or [])

        if "genre" in dims and not target.genres:
            result.violations.append(Violation_(
                "evidence", path, f"声称同流派，但候选 {tid} 没有任何流派标签"))
        if "mood" in dims and target.arousal is None:
            result.violations.append(Violation_(
                "evidence", path,
                f"声称能量相近，但候选 {tid} 没有实测音频特征（推断值不能支撑这个断言）"))
        if "artist" in dims:
            user_artists = {t.artist_id for t in ctx.tracks if t.artist_id}
            if target.artist_id not in user_artists:
                result.violations.append(Violation_(
                    "evidence", path, f"声称同艺人，但候选 {tid} 的艺人不在用户曲库里"))

        # --- 断言「有关系」就必须有锚点 ---
        rel = rec.get("relation_to_history") or {}
        if rel.get("note") and not rel.get("anchors"):
            result.violations.append(Violation_(
                "evidence", path,
                "写了「和用户听过的某首歌有关」但没给锚点 —— 无法核对，等于没解释"))
```

---

## 4. `tests/test_validate.py`

**关键：用真实失败样本做回归，不要自己编测试数据。**

```python
"""验证器的测试。用的全是 Phase 2 真实跑出来的失败样本。"""

from __future__ import annotations

import pytest

from musicmind_agent.validate import validate
from musicmind_agent.validate.normalize import (
    name_matches, numeric_forms, parse_cn_number,
)


# ---------- 归一化 ----------

@pytest.mark.parametrize("text,expected", [
    ("三", 3.0), ("十", 10.0), ("十二", 12.0), ("二十", 20.0),
    ("三成", 0.3), ("一半", 0.5), ("七成", 0.7),
])
def test_parse_cn_number(text, expected):
    assert parse_cn_number(text) == pytest.approx(expected)


def test_numeric_forms_covers_percent_and_decimal():
    """0.6835 在报告里可能写成 68.3%、68%、0.68 —— 都要能绑上。"""
    forms = numeric_forms(0.6835)
    assert "68.3%" in forms
    assert "0.68" in forms


def test_name_matches_across_scripts():
    """繁简。这个仓库已经栽过两次，别再栽第三次。"""
    assert name_matches("薛之谦", "薛之謙")
    assert name_matches("Jay Chou", "jay chou")


# ---------- L1 结构层：qwen 的真实失败样本 ----------

def test_fabricated_fact_key_is_caught(fake_ctx_double):
    """qwen 写了 mood.arousal_measured_median —— 这个键不存在。

    它把 arousal_measured_mean/min/max 和 arousal_median 两组名字拼在了一起。
    """
    report = {
        "headline": {"title": "t", "subtitle": ""},
        "dimensions": [{
            "dimension": "mood_energy",
            "summary": "",
            "claims": [{
                "text": f"中位数是 {{mood.arousal_measured_median}}",
                "metric_refs": [{"key": "mood.arousal_measured_median", "expect": None}],
                "evidence_track_ids": [],
                "basis": "data",
            }],
        }],
        "recommendations": [], "limitations": [],
    }
    result = validate(report, fake_ctx_double)
    assert not result.ok
    assert any(v.layer == "structure" and "arousal_measured_median" in v.detail
               for v in result.errors)


def test_claim_without_ref_or_evidence_is_warned(fake_ctx_double):
    """空口断言：既没引用事实也没证据。"""
    report = {
        "headline": {"title": "t", "subtitle": ""},
        "dimensions": [{
            "dimension": "genre", "summary": "",
            "claims": [{"text": "你很喜欢音乐", "metric_refs": [],
                        "evidence_track_ids": [], "basis": "data"}],
        }],
        "recommendations": [], "limitations": [],
    }
    result = validate(report, fake_ctx_double)
    assert any(v.layer == "structure" and v.severity == "warning" for v in result.warnings)


# ---------- L5 证据层：deepseek 第一版的真实失败样本 ----------

def test_evidence_from_candidate_pool_is_caught(fake_ctx_double):
    """第一版把推荐候选的 id 当成了用户的歌 —— 34 条证据全部越界。"""
    report = {
        "headline": {"title": "t", "subtitle": ""},
        "dimensions": [{
            "dimension": "genre", "summary": "",
            "claims": [{"text": "证据", "metric_refs": [],
                        "evidence_track_ids": [999999], "basis": "data"}],
        }],
        "recommendations": [], "limitations": [],
    }
    result = validate(report, fake_ctx_double, candidate_ids={999999})
    assert any(v.layer == "evidence" and "候选" in v.detail for v in result.errors)
```

**`fake_ctx_double` 是个 fixture**：构造一个最小的 ToolContext，带几条假曲目和几个真 facts。
放在 `tests/conftest.py` 里。**不要连真数据库** —— 这一组测的是逻辑，不是数据。

另外**必写一条端到端**：拿 `out/report-34-qwen.json` 跑一遍，断言
`mood.arousal_measured_median` 被 L1 抓到。（文件在 `out/` 里且被 gitignore，
所以这条测试要能优雅跳过 —— 文件不存在就 `pytest.skip`。）

---

## 5. `cli.py` 加 `validate` 子命令

```python
def cmd_validate(args: argparse.Namespace) -> int:
    from musicmind_agent.tools import build_context, call, core_tool_names
    from musicmind_agent.validate import validate

    report = json.load(open(args.report, encoding="utf-8"))["report"]

    connection = get_connection()
    try:
        ctx = build_context(connection, args.user)
        # facts 仓要靠跑工具填满 —— 报告里的键就来自这里
        for name in core_tool_names():
            call(name, ctx)
        result = validate(report, ctx)
    finally:
        connection.close()

    print(result.summary())
    return 0 if result.ok else 1
```

验收时 `--user` 要和生成报告时一致，否则 facts 仓对不上，会把好报告全判成违规。
**这是这个设计的已知约束**：验证依赖「同一个上下文」。

---

## 怎么跑

```bash
cd agent-service

# 单测（快、离线）
.venv/Scripts/python.exe -m pytest -q

# 拿两份真实报告验收
.venv/Scripts/python.exe -m musicmind_agent.cli validate --report out/report-34.json --user 34
.venv/Scripts/python.exe -m musicmind_agent.cli validate --report out/report-34-qwen.json --user 34
```

---

## 验收标准

1. **单测全绿**，且 `pytest -q` 仍在 1 秒内（验证器不能依赖网络/数据库）
2. **deepseek 报告：0 error**（它现在已经干净了，验证器不该误伤）
3. **qwen 报告：至少抓到 1 个 error**，且是 `mood.arousal_measured_median`
4. **误报率**：警告可以有，但 error 不能有假阳性 —— 误判会让 Phase 4 白白重写
5. **把 `violations` 的措辞写得像给模型看的**：Phase 4 会把它们原文回灌给 LLM 让它改，
   「引用了不存在的事实 X」比「校验失败 #3」有用得多

---

## 三个坑

1. **`walk_texts` 必须覆盖每一个 LLM 写的字段**。第一版漏了 `limitations`，
   那里面就带着没渲染的花括号原样输出了。**漏一个字段就是一个洞。**
2. **验证器要能优雅处理空报告**（模型返回了空 dimensions）—— 不能抛异常，
   要让 Phase 4 能拿到「哪里不对」而不是一个 traceback。
3. **繁简归一化**（`name_variants`）。这个仓库已经栽过两次，`validate/normalize.py`
   里直接复用 `zhconv`。

---

## 写完发我什么

1. `pytest -q` 的输出
2. 两份报告的 `validate` 输出（deepseek 应该全过，qwen 应该抓到那个 key）
3. 你觉得哪条规则写得太严或太松 —— **误报和漏报的取舍是这一步最需要判断力的地方**，
   我希望你带着自己的意见来找我，而不是只交一份能跑的代码
