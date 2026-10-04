# Phase 2 交接：LLM 接入 + 单次报告

**这一步是你写，我验收。** 目标：`python -m musicmind_agent.cli report --user 34 --provider deepseek`
产出一份报告 JSON（还没验证器，那是 Phase 3）。

---

## 起点：Phase 1 已经给你准备好的东西

```python
from musicmind_agent.tools import build_context, call, catalog, core_tool_names

ctx = build_context(connection, user_id)   # 数据一次取全
result = call("genre_distribution", ctx)   # 跑一个工具
result.facts        # {"genre.album.mandopop.share": 0.6835, ...}  ← 报告只能引用这些
result.rows         # 给 LLM 读的结构化行
result.evidence     # [{track_id, name, artist, why}]  能指回具体歌
result.coverage     # {considered, with_attribute, ratio, note}  必填
ctx.facts           # 全局事实仓（所有工具 facts 的合并）
```

CLI 现在能跑：`python -m musicmind_agent.cli tools --user 34`

**你要加的是：把工具输出喂给 LLM，让它写一份结构化报告。**

---

## 要建的文件（5 个）

```
agent-service/
  musicmind_agent/
    llm.py              ← 1. provider 注册表 + 统一调用
    models.py           ← 2. 报告的 pydantic 模型
    prompts/
      __init__.py
      compose.py        ← 3. compose 节点的 prompt
    report.py           ← 4. 组装：跑工具 → 调 LLM → 产出报告
    cli.py              ← 5. 加一个 report 子命令（改现有文件）
```

---

## 1. `musicmind_agent/llm.py`

```python
"""LLM 调用。DeepSeek 和通义千问走同一套代码，切换只改环境变量。

【为什么两家都要能跑】评估要证明「质量」不是某一家的特性。
而且一旦为某家写了特化 prompt，评估就失去意义 —— 你测的变成了
「这家模型 + 我的特化 prompt」而不是「我的系统」。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import requests

from musicmind_agent.config import LLM_PROVIDERS


class LLMError(Exception):
    pass


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


@dataclass
class LLMClient:
    provider: str
    temperature: float = 0.3
    timeout: int = 120
    max_retries: int = 2

    config: dict = field(init=False)
    session: requests.Session = field(init=False)

    def __post_init__(self):
        if self.provider not in LLM_PROVIDERS:
            raise LLMError(f"不认识的 provider：{self.provider}，可选 {list(LLM_PROVIDERS)}")
        self.config = LLM_PROVIDERS[self.provider]
        if not self.config["api_key"]:
            raise LLMError(f"{self.provider} 的 API key 没配（.env 里加 {self.provider.upper()}_API_KEY）")
        if not self.config["model"]:
            raise LLMError(f"{self.provider} 的模型名没配（.env 里加 {self.provider.upper()}_MODEL）")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json",
        })

    def chat(self, messages: list[dict], json_mode: bool = False) -> LLMResponse:
        """发一次对话。json_mode=True 时要求返回合法 JSON。

        【温度必须显式设置】两家的默认都是 1.0，评估要可复现就得压下来。
        """
        payload = {
            "model": self.config["model"],
            "messages": messages,
            "temperature": self.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error = None
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            try:
                response = self.session.post(
                    f"{self.config['base_url']}/chat/completions",
                    json=payload,
                    timeout=self.timeout,
                )
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                time.sleep(2 * (attempt + 1))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                time.sleep(2 * (attempt + 1))
                continue
            if response.status_code != 200:
                raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")

            data = response.json()
            usage = data.get("usage") or {}
            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                provider=self.provider,
                model=self.config["model"],
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        raise LLMError(f"重试 {self.max_retries} 次仍失败：{last_error}")

    def chat_json(self, messages: list[dict]) -> tuple[dict, LLMResponse]:
        """要一段 JSON。解析失败回灌一次 —— 千问的兼容层偶尔会包 ```json 围栏。"""
        response = self.chat(messages, json_mode=True)
        try:
            return json.loads(response.content), response
        except json.JSONDecodeError:
            pass

        cleaned = response.content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]

        try:
            return json.loads(cleaned), response
        except json.JSONDecodeError as e:
            # 回灌一次：把解析错误告诉它，让它重发
            retry_messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": f"这不是合法 JSON（{e}）。只输出 JSON，不要解释、不要围栏。"},
            ]
            retry = self.chat(retry_messages, json_mode=True)
            try:
                return json.loads(retry.content), retry
            except json.JSONDecodeError as e2:
                raise LLMError(f"两次都拿不到合法 JSON：{e2}")
```

**`.env` 要加（我不碰 .env，你自己加）**：

```
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-chat
QWEN_API_KEY=sk-xxx
QWEN_MODEL=qwen-plus
```

---

## 2. `musicmind_agent/models.py`

```python
"""报告的数据结构。

【数字只能以 metric_ref 的形式出现】LLM 不写数值、只写 `{fact.key}` 占位符，
渲染时替换。这样「编造一个数字」在结构上就写不出来。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MetricRef(BaseModel):
    """对一条事实的引用。expect 是 LLM 以为的值，验证器会拿它和实际值比。"""
    key: str
    expect: float | None = None


class Claim(BaseModel):
    text: str                                    # 叙事，数字写 {fact.key}
    metric_refs: list[MetricRef] = Field(default_factory=list)
    evidence_track_ids: list[int] = Field(default_factory=list)
    basis: Literal["data", "inference"] = "data"


class Dimension(BaseModel):
    dimension: Literal[
        "genre", "era", "artist", "mood_energy",
        "album_form", "duration", "diversity", "collaboration", "region",
    ]
    summary: str
    claims: list[Claim] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class RelationToHistory(BaseModel):
    """原则 4 的第三问：和用户过去喜欢的音乐有什么关系。"""
    anchors: list[int] = Field(default_factory=list)   # 必须是用户集里真实存在的 track_id
    note: str = ""


class Recommendation(BaseModel):
    track_id: int
    reason: str
    matched_dimensions: list[str] = Field(default_factory=list)   # 会被回查证实
    relation_to_history: RelationToHistory = Field(default_factory=RelationToHistory)
    rank: int = 0


class Headline(BaseModel):
    title: str
    subtitle: str = ""


class ReportDraft(BaseModel):
    """LLM 直接产出的东西。渲染和验证在这之后做。"""
    headline: Headline
    dimensions: list[Dimension] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
```

**要装 pydantic**：`.venv/Scripts/python.exe -m pip install pydantic`

---

## 3. `musicmind_agent/prompts/compose.py`

```python
"""compose 节点的 prompt。

【同一份 prompt 喂两家，不存在 provider 分支】一旦为某家特化，
评估测的就变成「模型 + 我的特化 prompt」，不是系统本身。
"""

# 改 prompt 必须升版本 —— 报告行里记着它，换版本后能区分
# 「质量变了」是模型换了还是 prompt 改了
PROMPT_VERSION = "compose-1.0"

SYSTEM = """你是音乐分析师。基于给定的数据事实，写一份用户音乐口味画像。

硬规则（违反会导致报告被自动打回重写）：

1. **不许写任何具体数字**。要提数字就写占位符 `{事实的key}`，比如
   「你有 {genre.album.mandopop.share} 的歌是 mandopop」。
   渲染时会自动替换成真值。自己编一个数字 = 报告作废。

2. **不许提没有数据支撑的维度**。库里没有播放行为、没有音频的情绪效价、
   没有乐评语料。情绪只谈「能量」（实测的），不要断言「伤感」「欢快」，
   除非你引用的是流派推断那一档并且明说了是推断。

3. **每条结论必须挂证据**。evidence_track_ids 里放用户曲目的真实 id。
   一个都没有的结论不要写。

4. **区分实测和推断**。能量是实测的（30 秒音频算的）；效价是流派推断的，
   粒度粗。报告里必须说清楚哪句是哪种。

5. **百分比要带分母**。覆盖率低的时候（比如只有 32% 的歌有专辑级流派），
   结论要说清是在多少首歌上算的。
"""

USER_TEMPLATE = """## 用户数据概览

{overview}

## 各维度的工具输出

{tool_results}

## 工具目录里可选的探针（这一轮没跑）

{probe_catalog}

## 要求

产出 JSON，结构如下：

{{
  "headline": {{"title": "...", "subtitle": "..."}},
  "dimensions": [
    {{
      "dimension": "genre|era|artist|mood_energy|album_form|duration|diversity|collaboration|region",
      "summary": "一句话概括",
      "confidence": "high|medium|low",
      "claims": [
        {{
          "text": "叙事，数字写 {{fact.key}}",
          "metric_refs": [{{"key": "fact.key", "expect": null}}],
          "evidence_track_ids": [123, 456],
          "basis": "data|inference"
        }}
      ]
    }}
  ],
  "recommendations": [
    {{
      "track_id": 789,
      "reason": "为什么推荐它",
      "matched_dimensions": ["genre", "era"],
      "relation_to_history": {{"anchors": [123], "note": "和用户听过的什么有关系"}},
      "rank": 1
    }}
  ],
  "limitations": ["这套数据做不到什么"]
}}

至少覆盖 genre / era / artist / mood_energy 四个维度。
推荐 5 首，track_id 必须来自候选列表。
"""
```

**`prompts/__init__.py`** 留空即可。

---

## 4. `musicmind_agent/report.py`

```python
"""组装一份报告：跑工具 → 喂给 LLM → 渲染 → 存下来。

Phase 2 只做「生成 + 渲染」，验证器是 Phase 3。
所以这个文件里【故意没有】校验逻辑 —— 先把链路跑通，再上一层层防线。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from musicmind_agent.llm import LLMClient, LLMResponse
from musicmind_agent.models import ReportDraft
from musicmind_agent.prompts.compose import PROMPT_VERSION, SYSTEM, USER_TEMPLATE
from musicmind_agent.render import render_text
from musicmind_agent.tools import build_context, call, catalog, core_tool_names


@dataclass
class GeneratedReport:
    draft: ReportDraft
    facts: dict
    rendered: dict          # 数字已经替换成真值的版本
    usage: dict


def _format_overview(ctx) -> str:
    """给 LLM 看的概览。只放事实，不放原始行 —— 它会淹没在数据里。"""
    lines = []
    for key, value in sorted(ctx.facts.items()):
        lines.append(f"- {key} = {value}")
    return "\n".join(lines)


def _format_tool_results(ctx, results) -> str:
    blocks = []
    for name, result in results.items():
        blocks.append(f"### {name}")
        blocks.append(f"facts: {json.dumps(result.facts, ensure_ascii=False)}")
        if result.rows:
            blocks.append(f"rows: {json.dumps(result.rows[:10], ensure_ascii=False)}")
        if result.coverage:
            blocks.append(f"coverage: {json.dumps(result.coverage, ensure_ascii=False)}")
        if result.warnings:
            blocks.append(f"warnings: {result.warnings}")
        blocks.append("")
    return "\n".join(blocks)


def build_report(connection, user_id: int, provider: str, client: LLMClient | None = None) -> GeneratedReport:
    ctx = build_context(connection, user_id)

    # Tier 0 全都跑。核心维度固定，不让 LLM 决定查不查
    results = {name: call(name, ctx) for name in core_tool_names()}

    client = client or LLMClient(provider=provider)

    # 推荐候选：先跑一次 similar_tracks 拿到候选列表给 LLM 挑
    # （Phase 5 会换成正式的五路召回，这里先用最简单的）
    from musicmind_agent.tools.base import ToolContext   # noqa
    seeds = [t.track_id for t in sorted(
        ctx.tracks, key=lambda t: -(t.arousal or 0))[:5]]
    candidates = call("similar_tracks", ctx, {"seed_track_ids": seeds, "limit": 30})

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER_TEMPLATE.format(
            overview=_format_overview(ctx),
            tool_results=_format_tool_results(ctx, results)
                          + "\n### similar_tracks（推荐候选）\n"
                          + json.dumps(candidates.rows, ensure_ascii=False),
            probe_catalog=json.dumps(catalog(tier=1), ensure_ascii=False, indent=1),
        )},
    ]

    raw, response = client.chat_json(messages)
    draft = ReportDraft.model_validate(raw)

    return GeneratedReport(
        draft=draft,
        facts=ctx.facts,
        rendered=_render(draft, ctx.facts),
        usage={
            "provider": response.provider,
            "model": response.model,
            "tokens_in": response.tokens_in,
            "tokens_out": response.tokens_out,
            "latency_ms": response.latency_ms,
            "prompt_version": PROMPT_VERSION,
        },
    )


def _render(draft: ReportDraft, facts: dict) -> dict:
    """把所有 {fact.key} 换成真值。strict=False —— Phase 2 先看有多少没替换上，
    Phase 3 的验证器会把它变成硬失败。"""
    data = draft.model_dump()
    data["headline"]["title"] = render_text(data["headline"]["title"], facts, strict=False)
    data["headline"]["subtitle"] = render_text(data["headline"]["subtitle"], facts, strict=False)
    for dim in data["dimensions"]:
        dim["summary"] = render_text(dim["summary"], facts, strict=False)
        for claim in dim["claims"]:
            claim["text"] = render_text(claim["text"], facts, strict=False)
    for rec in data["recommendations"]:
        rec["reason"] = render_text(rec["reason"], facts, strict=False)
        rec["relation_to_history"]["note"] = render_text(
            rec["relation_to_history"]["note"], facts, strict=False)
    return data
```

---

## 5. 改 `cli.py`：加 `report` 子命令

在 `main()` 里加：

```python
    p_report = sub.add_parser("report", help="生成一份音乐人格报告")
    p_report.add_argument("--user", type=int, required=True)
    p_report.add_argument("--provider", default="deepseek", choices=["deepseek", "qwen"])
    p_report.add_argument("--out", help="把报告写到这个文件（默认打印到屏幕）")
    p_report.set_defaults(func=cmd_report)
```

再加函数：

```python
def cmd_report(args: argparse.Namespace) -> int:
    from musicmind_agent.report import build_report

    connection = get_connection()
    try:
        report = build_report(connection, args.user, args.provider)
    except Exception as e:
        print(f"生成失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        connection.close()

    payload = {"report": report.rendered, "usage": report.usage}

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"已写入 {args.out}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    print(f"\n{report.usage['provider']}/{report.usage['model']}  "
          f"in={report.usage['tokens_in']} out={report.usage['tokens_out']}  "
          f"{report.usage['latency_ms']}ms", file=sys.stderr)
    return 0
```

---

## 怎么跑

```bash
cd agent-service

# 先确认工具层还是好的（不该被你的改动影响）
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m musicmind_agent.cli tools --user 34

# 跑报告
.venv/Scripts/python.exe -m musicmind_agent.cli report --user 34 --provider deepseek --out out/report-34.json
.venv/Scripts/python.exe -m musicmind_agent.cli report --user 34 --provider qwen --out out/report-34-qwen.json
```

---

## 验收标准

1. **两家都能出报告**，各连续跑 3 次不报错
2. **没有任何 `{...}` 残留**在渲染后的文本里 —— 有残留说明引用了不存在的事实
3. **报告里没有裸数字**（除了年份这类）：用 `find_bare_numbers()` 扫一遍，
   出现的数字要能对上某条事实
4. **推荐的 track_id 都在候选列表里**
5. **mood_energy 维度明确区分了实测和推断**

**把两份报告贴给我，我来验收。** 我会重点看：
- 有没有编造的数字或事实名
- 能量/效价的措辞有没有把推断说成实测
- 结论和工具输出对不对得上

---

## 两个坑（我在这个仓库里踩过，提前说）

1. **Windows 下 Python 输出重定向走 GBK**，print 中文和 ✓ 会抛异常。
   写文件时显式 `encoding="utf-8"`，写 JSON 时 `ensure_ascii=False`。
2. **`.env` 我不碰**（密钥是你的红线）。上面那四个变量你自己加。
