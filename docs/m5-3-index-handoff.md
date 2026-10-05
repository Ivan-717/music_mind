# M5.3 交接：分块 + embedding + Qdrant

**这一步是你的。** 目标：把 625 个语料文件切成块、算成向量、灌进 Qdrant，
让「我想了解 Britpop」这类问题**能从语料里检索到东西**。

---

## 起点

```
语料    .data/corpus/  625 个文件（artists 504 / genres 121），832 万字
分块    musicmind_agent/chunk.py —— 【我已经写了并测过】，见下面的「现状」
```

**先说清楚现状，免得你以为要从零开始**：我越界把 `chunk.py` 写了。
它跑通了（13,189 块，中位 713 字），设计决策都在注释里。
**你可以接着用、改、或者整个推翻重写** —— 那是你的步骤，你说了算。

`build_index.py` **我没写**，下面只给规格。

---

## 一、分块的设计（`chunk.py`，已存在）

### 三个参数和它们的理由

```python
TARGET_CHARS = 450   # 攒到这么大就交块
MAX_CHARS    = 800   # 单段超长才硬切
MIN_CHARS    = 120   # 短于这个的块并给邻居
```

**为什么按段落切、不按固定长度切**：维基正文的段落本身就是语义完整的单元。
按 500 字硬切会把一句话劈成两半，**而那半个句子在检索时是纯噪声** ——
它和任何查询都沾一点边，又都不太像，于是经常挤掉真正该命中的块。

### 实测踩到的两个坑（都已修，但你要理解为什么）

**① 主循环会漏下小尾巴。** 它只在两种情况下交块：攒够 TARGET、或者下一块会撑破 MAX。
两种都会留下残渣 —— 实测跑出 **877 个不足 100 字的块，最短 2 个字**。
所以有一趟 `_merge_tiny` 的后处理。

**② `_hard_split` 的尾巴更糟。** 整段只比 MAX 多几个字时，尾片只剩 1-2 个字。
那是**切分的残渣，不是内容** —— 并回前一块，宁可那一块略微超过 MAX。

修完：877 → 207 个不足 100 字的块，最短 2 → 10 字。剩下的 207 个是本身就很短的存根页。

### payload：写进去就改不了了

```python
{"kind": "artist", "id": 173, "name": "周杰倫", "lang": "zh",
 "page_title": "周杰倫", "chunk_index": 3, "chars": 412,
 "tracks_in_library": 788}
```

**`tracks_in_library` 尤其要紧** —— 它让检索能偏向用户真的在听的艺人。
788 首的周杰倫和只有 1 首的 session musician 不该被平等对待。
**Qdrant 只能按写入时的 payload 过滤，事后补就得重建整个索引。**

---

## 二、`build_index.py` 的规格（你要写的）

### 阻塞：embedding 从哪来

计划选的是 **Ollama + bge-m3**（模型落 D 盘，Python 侧一个依赖都不装）。
但实测**卡在网络上**：

```
ollama pull all-minilm
→ tls: failed to verify certificate: x509: certificate is not valid for any names,
  but wanted to match dd20bb891979d25aebc8bec07b2b3bbc.r2.cloudflarestorage.com
```

Ollama 从 Cloudflare R2 拉 blob，TLS 被中间人拦了。**这不是配置问题。**

```bash
# 你要跑的
ollama pull bge-m3
```

**如果它一直失败**，两条退路：
- `ollama pull all-minilm`（46MB，小得多，可能能过；但**中文弱**）
- 退回 `pip install "qdrant-client[fastembed]"`，**但必须把 `HF_HOME` 指到 D 盘**
  （它默认下到 `C:\Users\DELL\.cache\huggingface`，正撞在你只剩 17G 的那块盘上）

**所以 `build_index.py` 里 embedder 要做成一个可替换的小接口** ——
别把 URL 写死在主流程里。

### 完整代码

```python
"""把语料切块、算向量、灌进 Qdrant。

用法：
    python build_index.py --status          # 只报进度，不干活
    python build_index.py --kind genre      # 只灌流派（4,802 块，快）
    python build_index.py --limit 20        # 只灌前 20 个实体
    python build_index.py                   # 灌全部（约 13,000 块）

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
# 一次发几块。太小 → 13,000 块变成几千次 HTTP；太大 → 单次超时
BATCH = 16


# ============================================================
# embedding：做成可替换的
# ============================================================

def embed(texts: list[str], model: str = EMBED_MODEL) -> list[list[float]]:
    """一批文本 → 一批向量。

    【为什么单独一个函数】embedding 的来源是这一步唯一的未知数
    （Ollama 的 pull 卡在 TLS 上）。主流程不该知道它是 HTTP 还是 ONNX ——
    换来源时只改这一个函数。
    """
    resp = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": model, "input": texts},
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"embedding 失败 HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"embedding 失败：{data['error']}")
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
    # 按 kind/lang 过滤是常规查询，给它们建索引（小数据量其实无所谓，
    # 但建索引是按真实用法写的，以后数据涨了不用回来补）
    for field in ("kind", "lang", "id"):
        client.create_payload_index(COLLECTION, field, models.PayloadSchemaType.KEYWORD)


def done_entities(client: QdrantClient) -> set[tuple[str, int]]:
    """已经在库里的 (kind, id)。断点续跑靠它。

    【为什么敢全量 scroll】本地模式、一万多个点，一次扫完是秒级的。
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
    """一个实体的块：先删旧的再插新的。**顺序不能反。**"""
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
        # 重跑时是覆盖而不是新增。虽然上面已经删过一遍了，但两道都留着，
        # 因为「删漏了」和「插入失败」是两件不同的事
        pid = uuid.uuid5(uuid.NAMESPACE_URL,
                         f"{kind}/{eid}/{chunk.payload['lang']}/{chunk.payload['chunk_index']}")
        points.append(models.PointStruct(id=str(pid), vector=vector, payload=chunk.payload))
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
        print(f"{kind}：{n}/{len(files)} 已灌，collection 共 {client.count(COLLECTION).count} 块")
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
                batch = chunks[start:start + BATCH]
                vectors.extend(embed([c.text for c in batch]))

            if not vectors or len(vectors) != len(chunks):
                raise RuntimeError(f"向量数对不上：{len(vectors)} vs {len(chunks)}")

            if not client.collection_exists(COLLECTION):
                # 维度从第一批真实向量里拿 —— 不写死，换模型时不用改代码
                ensure_collection(client, len(vectors[0]))

            n = replace_entity(client, entity, vectors)
            indexed += 1
            total_points += n
            print(f"[{i}/{len(files)}] {entity['name'][:20]} {n} 块")
        except Exception as e:
            # 【不打标记，不写空】失败就跳过，下次重跑自然重试 ——
            # 和抓语料同一个规矩：写个失败标记 = 把一次抖动永久记成已处理
            failed += 1
            print(f"[{i}/{len(files)}] {entity['name'][:20]} ✗ {type(e).__name__}: {str(e)[:80]}")

    print()
    print("=" * 60)
    print(f"{kind}：新灌 {indexed} 个实体（{total_points} 块）  跳过 {skipped}  失败 {failed}")
    print(f"耗时 {(time.time()-started)/60:.1f} 分钟")
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
```

### 顺手补一个洞

`agent-service/requirements.txt` **不存在** —— 依赖是随手装进 venv 的，换台机器复现不出来。
这一步要加 `qdrant-client`，把这份补上：

```
pymysql
python-dotenv
requests
zhconv
langgraph
langgraph-checkpoint-sqlite
librosa
soundfile
numpy
qdrant-client
```

---

## 三、验收

```
1. --status 能报进度，不干活
2. collection 的 count == 所有实体的块数之和（没有静默丢块）
3. 断点续跑：重跑一次同一个命令 → 全部跳过，秒级结束
4. 幂等：删掉某个实体的点再重跑 → 块数【不变】（不是翻倍）
5. payload 过滤能生效：filter lang=zh 只返回中文块
6. 【最关键】检索测试：
   · 「Britpop 是什么」        → genres 里的 britpop 排第一
   · 「周杰倫的音乐风格」       → artists 里的周杰倫
   · 「适合深夜听的音乐」       → 风格/流派类，而不是某个具体艺人
```

**前五条是工程正确性，只有第 6 条回答「这套语料到底能不能用」。**
前五条全绿而第 6 条不对的话，问题在分块或模型，不在管道。

第 6 条跑法（临时脚本就行）：

```python
from qdrant_client import QdrantClient
from musicmind_agent.chunk import ...   # 不用，直接用你的 embed()
client = QdrantClient(path=".data/qdrant")
for q in ["Britpop 是什么", "周杰倫的音乐风格", "适合深夜听的音乐"]:
    hits = client.query_points("musicmind_knowledge", query=embed([q])[0], limit=3).points
    print(q, "→", [(h.payload["kind"], h.payload["name"], round(h.score, 3)) for h in hits])
```

---

## 四、坑

1. **先删后插，顺序不能反。** 反了的话旧块还在，跑两次块数翻倍，
   而检索时同一段内容以两倍权重出现 —— 那种偏置看不出来
2. **失败不写标记。** 下次重跑自然重试（`fetch_corpus.py` 那边同一个规矩）
3. **向量维度别写死。** 从第一批真实向量里拿 —— 换 embedding 模型时不用改代码
4. **embedder 单独一个函数。** 它是这一步唯一的未知数（Ollama 的 pull 卡在 TLS），
   主流程不该知道它是 HTTP 还是 ONNX
5. **别一条一条 embed。** 13,000 块会变成 13,000 次 HTTP；批量 16 块
6. **`HF_HOME` 一定要指到 D 盘**（如果你走 fastembed 那条路）。
   默认是 `C:\Users\DELL\.cache\huggingface`，正撞在你缺空间的那块盘上
