"""把语料切块、算向量、灌进 Qdrant。

用法：
    python build_index.py --status          # 只报进度，不干活
    python build_index.py --kind genre      # 只灌流派（快）
    python build_index.py --limit 20        # 只灌前 20 个实体，先看通路
    python build_index.py                   # 全部

【断点续跑和幂等】和抓语料同一个规矩：
    · 已经在 collection 里的 (kind, id) 跳过
    · 重建某个实体时【先按 payload 删掉它的旧块再插】——
      不删的话跑两次块数翻倍，而检索时同一段内容会以两倍权重出现，
      那种偏置看不出来
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402
from qdrant_client import QdrantClient, models  # noqa: E402

from musicmind_agent.chunk import chunks_for  # noqa: E402
from musicmind_agent.config import PROJECT_ROOT  # noqa: E402

CORPUS_DIR = PROJECT_ROOT / "agent-service" / ".data" / "corpus"
QDRANT_PATH = PROJECT_ROOT / "agent-service" / ".data" / "qdrant"
COLLECTION = "musicmind_knowledge"

OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "bge-m3"
# 一次发几块。太小 → 上万块变成上万次 HTTP；太大 → 单次超时
BATCH = 16


# ============================================================
# embedding：做成可替换的
# ============================================================

def embed(texts: list[str], model: str = EMBED_MODEL) -> list[list[float]]:
    """一批文本 → 一批向量。

    【为什么单独一个函数】embedding 的来源是这一步**唯一的未知数**
    （实测 ollama pull 一开始卡在 TLS 上）。主流程不该知道它是 HTTP 还是 ONNX ——
    换来源时只改这一个函数。
    """
    resp = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": model, "input": texts},
        timeout=600,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if "error" in data:
        raise RuntimeError(str(data["error"])[:200])
    return data["embeddings"]


# ============================================================
# Qdrant
# ============================================================

def open_client() -> QdrantClient:
    """本地文件模式 —— 和 checkpoints.db 放一起，不用起服务。

    【单进程排他锁】本地模式同时只允许一个进程打开。AgentWorker 是单线程，
    碰不上；哪天真并发起来，换成 `QdrantClient(url=...)` 指向 Docker 只改这一行。
    """
    QDRANT_PATH.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(QDRANT_PATH))


def ensure_collection(client: QdrantClient, dim: int) -> None:
    if client.collection_exists(COLLECTION):
        return
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )
    # 按 kind / lang / id 过滤是常规查询。数据量小的时候建不建都行，
    # 但按真实用法建上，以后数据涨了不用回来补
    for field in ("kind", "lang", "id"):
        client.create_payload_index(COLLECTION, field,
                                    models.PayloadSchemaType.KEYWORD)


def done_entities(client: QdrantClient) -> set[tuple[str, int]]:
    """已经在库里的 (kind, id)。断点续跑靠它。

    【为什么敢全量 scroll】本地模式、一万多个点，扫一遍是秒级的。
    换成「逐实体 count」反而要发一万多次请求。
    """
    out: set[tuple[str, int]] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            COLLECTION, limit=1000, offset=offset,
            with_payload=["kind", "id"], with_vectors=False,
        )
        for p in points:
            out.add((p.payload.get("kind"), p.payload.get("id")))
        if offset is None:
            break
    return out


def replace_entity(client: QdrantClient, entity: dict, vectors: list[list[float]]) -> int:
    """一个实体的块：**先删旧的再插新的，顺序不能反。**

    反了的话旧块还在，跑两次块数翻倍 —— 而检索时同一段内容会以两倍权重出现，
    那种偏置看不出来。
    """
    kind, eid = entity["kind"], entity["id"]
    client.delete(
        COLLECTION,
        points_selector=models.FilterSelector(filter=models.Filter(must=[
            models.FieldCondition(key="kind", match=models.MatchValue(value=kind)),
            models.FieldCondition(key="id", match=models.MatchValue(value=eid)),
        ])),
    )

    points = []
    for chunk, vector in zip(chunks_for(entity), vectors):
        # 【id 用 uuid5，不用自增】同一块每次算出来的 id 一样 ——
        # 重跑时是覆盖而不是新增。上面那道删是防「实体变短了，旧块留下」，
        # 这一道是防「删漏了」。两道防的是不同的事
        pid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{kind}/{eid}/{chunk.payload['lang']}/{chunk.payload['chunk_index']}")
        points.append(models.PointStruct(id=str(pid), vector=vector,
                                         payload=chunk.payload))
    client.upsert(COLLECTION, points=points)
    return len(points)


# ============================================================
# 主流程
# ============================================================

def run(kind: str, limit: int | None, status_only: bool) -> None:
    client = open_client()

    files = sorted((CORPUS_DIR / f"{kind}s").glob("*.json"))
    if limit is not None:
        files = files[:limit]

    if status_only:
        if not client.collection_exists(COLLECTION):
            print(f"{kind}：collection 还没建（0/{len(files)}）")
            return
        done = done_entities(client)
        n = sum(1 for f in files
                if (kind, json.loads(f.read_text(encoding="utf-8"))["id"]) in done)
        print(f"{kind}：{n}/{len(files)} 已灌，"
              f"collection 共 {client.count(COLLECTION).count} 块")
        return

    done = done_entities(client) if client.collection_exists(COLLECTION) else set()

    started = time.time()
    indexed = skipped = failed = 0
    total_points = 0

    for i, path in enumerate(files, start=1):
        entity = json.loads(path.read_text(encoding="utf-8"))
        if (entity["kind"], entity["id"]) in done:
            skipped += 1
            continue

        chunks = chunks_for(entity)
        if not chunks:
            skipped += 1
            continue

        try:
            vectors: list[list[float]] = []
            for start in range(0, len(chunks), BATCH):
                vectors.extend(embed([c.text for c in chunks[start:start + BATCH]]))

            if len(vectors) != len(chunks):
                raise RuntimeError(f"向量数对不上：{len(vectors)} vs {len(chunks)}")

            if not client.collection_exists(COLLECTION):
                # 维度从第一批真向量里拿 —— 不写死，换模型时不用改代码
                ensure_collection(client, len(vectors[0]))

            n = replace_entity(client, entity, vectors)
            indexed += 1
            total_points += n
            print(f"[{i}/{len(files)}] {entity['name'][:22]} {n} 块")
        except Exception as e:
            # 【不打标记，不写空】失败就跳过，下次重跑自然重试 ——
            # 和抓语料同一个规矩：写个失败标记 = 把一次抖动永久记成已处理
            failed += 1
            print(f"[{i}/{len(files)}] {entity['name'][:22]} ✗ "
                  f"{type(e).__name__}: {str(e)[:80]}")

    print()
    print("=" * 60)
    print(f"{kind}：新灌 {indexed} 个实体（{total_points} 块）  "
          f"跳过 {skipped}  失败 {failed}")
    print(f"耗时 {(time.time() - started) / 60:.1f} 分钟")
    if client.collection_exists(COLLECTION):
        print(f"collection 现在共 {client.count(COLLECTION).count} 块")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="建向量索引（断点续跑）")
    parser.add_argument("--kind", default="all", choices=["artist", "genre", "all"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    kinds = ["genre", "artist"] if args.kind == "all" else [args.kind]
    for kind in kinds:
        run(kind, args.limit, args.status)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
