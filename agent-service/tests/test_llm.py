"""LLM 客户端的配置解析。全部离线 —— 不真的发请求。

【为什么值得单独测】这两条错了都不会在本地暴露：max_tokens 超上限是**服务端**返回
400，而返回的措辞（InvalidParameter）看起来像请求格式写错了，不像「我们把额度设大了」。
实测千问那条链就是这么整个挂掉的，而且挂了很多次都没人往配置上想。
"""

from __future__ import annotations

import pytest

import musicmind_agent.llm as llm
from musicmind_agent.config import LLM_PROVIDERS


def _fake(monkeypatch, **overrides):
    cfg = {"base_url": "http://example.invalid", "api_key": "k",
           "model": "m", "max_tokens": 1234}
    cfg.update(overrides)
    monkeypatch.setitem(llm.LLM_PROVIDERS, "fake", cfg)
    return "fake"


def test_max_tokens_comes_from_the_provider_registry(monkeypatch):
    """每家上限不同，所以默认值必须跟着 provider 走。"""
    name = _fake(monkeypatch, max_tokens=1234)
    assert llm.LLMClient(provider=name).max_tokens == 1234


def test_max_tokens_can_be_overridden(monkeypatch):
    name = _fake(monkeypatch, max_tokens=1234)
    assert llm.LLMClient(provider=name, max_tokens=99).max_tokens == 99


def test_registry_declares_a_limit_for_every_provider():
    """注册表里每一家都要有 max_tokens。

    漏了会静默退回 4096 —— 对上限 3072 的模型来说 4096 一样是超的，
    而「静默退回一个也不对的值」比直接报错更难查。
    """
    for name, cfg in LLM_PROVIDERS.items():
        assert isinstance(cfg.get("max_tokens"), int), f"{name} 没配 max_tokens"
        assert cfg["max_tokens"] > 0, f"{name} 的 max_tokens 必须为正"


def test_unknown_provider_is_rejected(monkeypatch):
    with pytest.raises(llm.LLMError, match="不认识的 provider"):
        llm.LLMClient(provider="no-such-provider")
