"""把语料切成块。

【为什么按段落切，不按固定长度】维基正文的段落本身就是语义完整的单元。
按 500 字硬切会把一句话劈成两半，而那半个句子在检索时是**纯噪声** ——
它和任何查询都沾一点边，又都不太像，于是经常挤掉真正该命中的块。

【三个数是怎么来的】
    TARGET 450  中文一段话的常见长度，也是「一块里能讲清一件事」的量级
    MAX 800     超过它就得切，不然一块里塞了三四件事，检索到也不知道是冲哪件来的
    MIN 250     太短的块（比如一个只有一句话的段落）单独成块时信息量不够，
                跟相邻的合起来更划算
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TARGET_CHARS = 450
MAX_CHARS = 800
# 短于这个的块要并给邻居。不并的话会留下「参见」「目录」这种孤零零的一行，
# 而它会被向量化成一条**噪声** —— 和任何查询都沾一点边，于是经常挤掉
# 真正该命中的块。实测第一版跑出 877 个不足 100 字的块，最短的只有 2 个字
MIN_CHARS = 120
# 段落之间用什么连。保留换行，让向量化时还能看出这是两段
JOIN = "\n"

# 句末标点。硬切时优先在这些地方下刀 —— 落在字中间就是半句话
_SENTENCE_END = "。！？!?…；;"


@dataclass
class Chunk:
    text: str
    payload: dict


def _hard_split(paragraph: str) -> list[str]:
    """一个超长段落切成几块。**尽量在句末下刀。**

    `rfind` 找窗口里最后一个句末；如果它落在窗口前半段，说明这一段后面
    大半句都没标点（列表、引用之类），只能在窗口末尾硬切 —— 那种情况下
    切在哪儿都差不多。
    """
    out: list[str] = []
    start = 0
    while len(paragraph) - start > MAX_CHARS:
        window = paragraph[start:start + MAX_CHARS]
        cut = max((window.rfind(c) for c in _SENTENCE_END), default=-1)
        if cut < MAX_CHARS // 2:
            cut = MAX_CHARS - 1
        piece = paragraph[start:start + cut + 1].strip()
        if piece:
            out.append(piece)
        start += cut + 1
    tail = paragraph[start:].strip()
    if tail:
        # 【尾巴太短就并回去】整段只比 MAX 多几个字时，尾片就只剩 1-2 个字 ——
        # 那是切分的残渣，不是内容（实测最短的块是 2 个字）。
        # 并回去的那一块会略微超过 MAX，但「超一点」远好过「一条噪声向量」
        if out and len(tail) < MIN_CHARS:
            out[-1] = f"{out[-1]}{tail}"
        else:
            out.append(tail)
    return out


def _merge_tiny(chunks: list[str]) -> list[str]:
    """把过短的块并给前一个。

    【为什么必须有这一趟】主循环只在两种情况下交块：攒够 TARGET、或者下一块
    会撑破 MAX。两种都会漏下小尾巴 —— 实测跑出 877 个不足 100 字的块，
    最短的只有 2 个字（那是一个「参见」之类的残留行）。

    并进去的时候仍然守着 MAX：前一块已经接近上限就让它单独留着，
    总比撑破好。
    """
    out: list[str] = []
    for chunk in chunks:
        if (out and len(chunk) < MIN_CHARS
                and len(out[-1]) + len(JOIN) + len(chunk) <= MAX_CHARS):
            out[-1] = f"{out[-1]}{JOIN}{chunk}"
        else:
            out.append(chunk)
    return out


def split_text(text: str) -> list[str]:
    """正文 → 块。空行分段，攒到 TARGET 收手，超 MAX 就切。"""
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    buf = ""
    for paragraph in paragraphs:
        pieces = _hard_split(paragraph) if len(paragraph) > MAX_CHARS else [paragraph]
        for piece in pieces:
            # 加上这一块会超上限 → 先把手上这坨交出去
            if buf and len(buf) + len(JOIN) + len(piece) > MAX_CHARS:
                chunks.append(buf)
                buf = ""
            buf = f"{buf}{JOIN}{piece}" if buf else piece
            # 攒够了就交，不硬等下一段 —— 否则一个 200 字的段落后面跟着
            # 一个好几百字的段落时，两块会粘成一个超长的
            if len(buf) >= TARGET_CHARS:
                chunks.append(buf)
                buf = ""

    if buf:
        chunks.append(buf)
    return _merge_tiny(chunks)


def chunks_for(entity: dict) -> list[Chunk]:
    """一个语料文件（`.data/corpus/<kind>s/<id>.json`）→ 它的全部块。

    payload 里每一列都是**事后补不回来的**：Qdrant 只能按写入时的 payload 过滤，
    要在检索时「只看中文的」「偏向用户真在听的艺人」，那些字段必须在写入时就带上。
    """
    meta = entity.get("meta") or {}
    base = {
        "kind": entity.get("kind"),
        "id": entity.get("id"),
        "name": entity.get("name"),
        # tracks_in_library 让检索能偏向用户真的在听的艺人 ——
        # 788 首的周杰倫和只有 1 首的 session musician 不该被平等对待
        **{k: v for k, v in meta.items() if v is not None},
    }

    out: list[Chunk] = []
    for page in entity.get("pages") or []:
        for i, text in enumerate(split_text(page.get("text") or "")):
            out.append(Chunk(text=text, payload={
                **base,
                "lang": page.get("lang"),
                "page_title": page.get("title"),
                "chunk_index": i,
                "chars": len(text),
                # 【正文必须进 payload】它才是检索真正要拿的东西 ——
                # 向量只负责「找到」，payload 才是「找到之后读什么」。
                # 第一版漏了它：检索命中、分数好看、正文是空的，
                # 而那种错在流水线上一路绿灯
                "text": text,
            }))
    return out
