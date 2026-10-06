from __future__ import annotations


from musicmind_agent.tools.base import ToolContext, ToolResult, cap_evidence, cov, register


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
            # 【单独给一列】路径解析要拿它去对「模型提到的名字有没有出处」。
            # 埋在「来源」那串里的话就得解析字符串 —— 那种解析迟早被格式改动打脸
            "名称": h["name"],
            "类型": h["kind"],
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