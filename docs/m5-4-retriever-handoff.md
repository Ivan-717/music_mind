# M5.4 交接：把语料接给 Agent

**这一步是你的。** 目标：注册一个 `search_knowledge` 工具，让对话能查语料 ——
这是 §3.1 第③条「我想了解 Britpop」的**最后一块**。

前置：M5.3 已完成，Qdrant 里 13,189 块，检索三条全中。

---

## 先说三个必须处理的现实

### ① 本地模式有单进程锁

`QdrantClient(path=...)` 同时只允许一个进程打开。Agent 是子进程，
所以：

```
对话在跑  +  build_index.py 在跑   → 有一个会被锁挡住
```

**不要试图「解决」它**，把错误说清楚就行：
「语料索引正在被另一个进程占用（多半是在重建索引），等它跑完再问」。
比「莫名其妙检索不到东西」好得多。

### ② 换 embedding 模型会让检索【静默】变噪声

不同模型算出来的向量在不同的空间里。换了模型只重建一半、
或者查询端还用着旧模型 —— 检索照样返回结果、分数照样是 0.6 几，
**只是全部不相干**。这类错没有任何东西会报警。

**所以：建索引时把模型名写进一份 manifest，查询前先对。对不上就拒绝返回。**

### ③ 语料里的数字不能进报告

`search_knowledge` 只给**对话**用，不给报告的探针用。
理由：语料里全是数字（年代、排行、销量），模型一旦引用，
报告的 L3 字面量层会把它判成「绑不到任何事实」→ 打回重写。

报告是「你的数据画像」，知识不是它的活。**所以注册成 Tier 2，不是 Tier 1。**

---

## 你要写的（3 处）

### 1. `musicmind_agent/knowledge.py` —— 新增

```python
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
```

**`build_index.py` 要跟着改两处**：

```python
# ① 换成 import，别再自己写一份 embed
from musicmind_agent.knowledge import EMBED_MODEL, MANIFEST, embed

# ② 建完之后写清单
def write_manifest(chunks: int, dim: int) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "model": EMBED_MODEL, "dim": dim, "chunks": chunks,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
```

### 2. 注册工具（`tools/explore.py` 末尾，或新开一个 `tools/knowledge.py`）

**注册成 Tier 2**（支撑），理由见前面第③条 —— 报告探针的白名单是 Tier 1，
这样就天然拿不到它。

```python
@register(
    "search_knowledge", 2,
    "查音乐知识语料（维基条目）：流派是什么、某个艺人的背景、某个运动的来龙去脉。"
    "**回答「为什么」「是什么」这类问题用它**；查用户自己的歌用别的工具",
    {
        "query": "要查的问题，尽量是一句完整的话而不是几个关键词",
        "kind": "限定 artist / genre，不传就是全部",
        "lang": "限定 zh / en，不传就是全部",
    },
)
def search_knowledge(ctx: ToolContext, args: dict) -> ToolResult:
    from musicmind_agent.knowledge import IndexUnavailable, search

    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(tool="search_knowledge", warnings=["缺少 query"])

    try:
        hits = search(query, limit=5, kind=args.get("kind"), lang=args.get("lang"))
    except IndexUnavailable as e:
        # 【必须变成 warning，不能抛】抛出去会被 call() 兜成「空结果」，
        # 而空结果和「语料里没有」长得一模一样 —— 模型会据此说
        # 「我的语料里没有这个」，而实际是索引没建好
        return ToolResult(tool="search_knowledge", warnings=[str(e)])

    if not hits:
        return ToolResult(tool="search_knowledge", warnings=["语料里没找到相关的内容"])

    return ToolResult(
        tool="search_knowledge",
        facts={"knowledge.hits": len(hits),
               "knowledge.top_score": hits[0]["score"]},
        rows=[{
            "来源": f"{h['kind']}／{h['page_title']}（{h['lang']}）",
            "相似度": h["score"],
            # 【截断】一块平均 700 字，5 条就是 3,500 字。全塞进 prompt
            # 会把工具目录和 facts 挤到窗口边缘
            "正文": h["text"][:600] + ("…" if len(h["text"]) > 600 else ""),
        } for h in hits],
        # 【evidence 必须是空的】它是「用户听过的曲目 id」的池子，
        # 而语料块根本不是用户的歌。填了会让 L5 证据回查层判越界
        evidence=[],
        coverage=cov(0, len(hits), "语料检索，不涉及用户的曲目"),
    )
```

### 3. `chat.py` 的 CHAT_SYSTEM 加一条规则

**这条不能省。** M3 已经证明过一次：光有工具不够，得在规则里说要它用 ——
当时用户问「推荐林俊杰」，模型**一个工具都没调**就直接说「做不到」了。

```python
- **问「是什么」「为什么」「有什么背景」这类知识和背景问题，用 `search_knowledge` 查语料。**
  比如「Britpop 是什么」「Oasis 和 Blur 为什么总被放在一起」。
  这些不在你的数据里，在语料里 —— **不要凭印象答，去查**。

  语料说的是音乐知识，不是用户的听歌记录。查回来的内容可以直接讲，
  但它**不是用户的歌**，不能拿它说「你听过……」。
```

---

## 验收

```
1. 问「Britpop 是什么」→ 回答里有实质内容（不只是「我的库里没有」）
   且 used_tools 里有 search_knowledge
2. 问「我听得最多的是什么流派」→ 【不应该】调 search_knowledge
   （那是用户数据，不是知识）
3. 把 .data/corpus_index.json 里的 model 改掉 → 检索应该【拒绝】
   并说清楚原因，而不是返回一堆不相干的
4. 索引不存在时（把 .data/qdrant 改名）→ 工具返回 warning，
   回答里说的应该是「索引没建好」，**不是「语料里没有」**
5. 报告的探针白名单里【没有】它（catalog(tier=1) 不含 search_knowledge）
6. pytest 离线全绿
```

**第 4 条是这一步最容易漏的**：`IndexUnavailable` 被兜成空结果的话，
「索引坏了」和「语料里没有」在模型眼里长得一样，它会自信地说后者。

---

## 坑

1. **模型名对不上必须拒绝。** 换模型后忘了重建，检索结果是**静默的噪声** ——
   分数好看、内容全不相干、没有任何东西报警
2. **`IndexUnavailable` 要变成 warning，不能让它抛。** 抛了会被 `call()` 兜成空结果
3. **`evidence` 必须是空的。** 语料块不是用户的歌，填进证据池会让 L5 判越界
4. **只注册成 Tier 2。** 进 Tier 1 就会出现在报告的探针白名单里，
   而语料里的数字会让 L3 字面量层把报告打回重写
5. **一个 Agent 进程只开一次 Qdrant。** 本地模式是排他锁，反复开关只会更容易撞上
6. **别在 `build_index.py` 跑的时候用对话。** 锁挡着，会拿到一句人话错误 ——
   那是**有意的**，比静默失败好
