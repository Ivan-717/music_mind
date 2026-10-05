"""查语料（RAG 的检索那一半）。

【为什么单独一个模块】两件事必须共用同一份实现：
    · 建索引（build_index.py）
    · 查询（Agent 的工具层）
  尤其是 embed() —— 两边用不同模型的话，向量落在不同的空间里，
  检索会【静默地】返回一堆不相干的东西，分数还很好看。

【和 build_index.py 的分工】那边负责写，这边负责读。
  embed() 两边都要用，所以放在这里，那边 import 过去
  （现在 build_index.py 里有一份自己的 embed，要换成 import）。
"""

from __future__ import annotations

import json
from pathlib import Path

import requests
from qdrant_client import QdrantClient, models

from musicmind_agent.config import PROJECT_ROOT

QDRANT_PATH = PROJECT_ROOT / "agent-service" / ".data" / "qdrant"
# 【索引清单放在 Qdrant 目录【外面】】那是它自己的地盘，别往里塞文件
MANIFEST = PROJECT_ROOT / "agent-service" / ".data" / "corpus_index.json"

COLLECTION = "musicmind_knowledge"
OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "bge-m3"


class IndexUnavailable(Exception):
    """索引没建好、被占用、或者模型对不上。**调用方要把它变成一句人话。**"""


def embed(texts: list[str]) -> list[list[float]]:
    """一批文本 → 一批向量。**建索引和查询共用这一个函数。**"""
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/embed",
                             json={"model": EMBED_MODEL, "input": texts}, timeout=300)
    except Exception as e:
        raise IndexUnavailable(f"连不上 Ollama（{type(e).__name__}）") from e
    if resp.status_code != 200:
        raise IndexUnavailable(f"embedding 失败 HTTP {resp.status_code}")
    data = resp.json()
    if "error" in data:
        raise IndexUnavailable(f"embedding 失败：{data['error']}")
    return data["embeddings"]


# 一个 Agent 进程只开一次。本地模式的锁是排他的，
# 反复开关只会把「占用中」的概率变大
_client: QdrantClient | None = None


def client() -> QdrantClient:
    global _client
    if _client is None:
        if not QDRANT_PATH.exists():
            raise IndexUnavailable("语料索引还没建（跑 build_index.py）")
        try:
            _client = QdrantClient(path=str(QDRANT_PATH))
        except Exception as e:
            # 本地模式是排他锁 —— 另一个进程开着时就是这个错
            raise IndexUnavailable(
                "语料索引正被另一个进程占用（多半是在重建索引），等它跑完再问") from e
    return _client


def check_model() -> None:
    """查询前先对模型名。**对不上就拒绝，不要返回一堆不相干的东西。**

    这是这一步唯一一处「主动挡自己」的检查，理由见文件头：
    换模型之后忘了重建索引，检索结果会静默变成噪声，
    而分数照样是 0.6 几 —— 没有任何东西会报警。
    """
    if not MANIFEST.exists():
        raise IndexUnavailable("找不到索引清单（跑 build_index.py）")
    meta = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if meta.get("model") != EMBED_MODEL:
        raise IndexUnavailable(
            f"索引是用 {meta.get('model')} 建的，现在配的是 {EMBED_MODEL} —— "
            f"要先重建索引（build_index.py）")


def search(query: str, limit: int = 5, kind: str | None = None,
           lang: str | None = None) -> list[dict]:
    """查语料。返回 [{text, kind, name, lang, page_title, score}]。

    kind: artist / genre　lang: zh / en　都可以不传。
    **不传 lang 是有意的** —— bge-m3 是多语言的，中文问题检索到英文条目
    往往是件好事（英文条目实测厚 2-4 倍）。
    """
    check_model()
    vector = embed([query])[0]

    conditions = []
    if kind:
        conditions.append(models.FieldCondition(key="kind",
                                                match=models.MatchValue(value=kind)))
    if lang:
        conditions.append(models.FieldCondition(key="lang",
                                                match=models.MatchValue(value=lang)))
    flt = models.Filter(must=conditions) if conditions else None

    try:
        hits = client().query_points(COLLECTION, query=vector, limit=limit,
                                     query_filter=flt).points
    except Exception as e:
        raise IndexUnavailable(f"检索失败：{type(e).__name__}") from e

    return [{
        "text": h.payload.get("text") or "",
        "kind": h.payload.get("kind"),
        "name": h.payload.get("name"),
        "lang": h.payload.get("lang"),
        "page_title": h.payload.get("page_title"),
        "score": round(float(h.score), 4),
    } for h in hits]