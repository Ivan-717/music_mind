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
    content:str
    provider:str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0

@dataclass
class LLMClient:
    provider:str
    temperature:float=0.3
    # 【超时不能按「正常情况」设】实测：千问 compose 一次要 60 秒以上，
    # 让它输出 50 条推荐时直接超过 120 秒 → ReadTimeout → 重试 2 次 → 整折失败。
    # 5 折全挂。评估用的是免费额度，宁愿慢也不要白跑
    timeout: int = 300
    # 单次生成的上限。**默认值在 provider 注册表里**（config.LLM_PROVIDERS），
    # 因为每家的硬上限不同 —— 详情见那边的注释。
    # None = 用这家注册表里的值；显式传一个数可以覆盖（测试用）
    max_tokens: int | None = None
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
        if self.max_tokens is None:
            self.max_tokens = self.config.get("max_tokens", 4096)
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json",
        })

    def chat(self, messages: list[dict], json_mode: bool = False) -> LLMResponse:
        """发一次对话。json_mode=True 时要求返回合法 JSON。

        【温度必须显式设置】两家的默认都是 1.0，评估要可复现就得压下来。

        【max_tokens 也必须显式设置】不设就走服务商默认值（deepseek 是 4096），
        而「50 条推荐 + 每条带理由 + 5 个维度带 claims」的输出远超这个数 ——
        结果是 JSON 被**从中间截断**，报 `Unterminated string starting at: line 565`。
        这个错看起来像「模型不会写 JSON」，实际是我们没给它足够的额度。
        实测：只推 5 条时一切正常，推到 50 条就必然触发。
        """
        payload = {
            "model": self.config["model"],
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
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













