"""对话：对用户的自然语言提问，查工具、回答，必要时给推荐。

【为什么不是新造一个 Agent】`ask.py` 已经是一个完整的工具循环了 ——
build_context → LLM 带目录 → 挑工具 → 白名单校验 → 结果回灌 → 回答 → 渲染数字。
这里做的是**把它泛化**：多读多轮历史，多输出一个推荐列表。

【和 ask 的区别】
    ask   锚定一份报告，上下文 = 报告 + 那份报告的 facts 快照
    chat  锚定用户，  上下文 = 现算的用户画像

【数字还是走引用】和报告同一条防线：模型不写数值，写 `{fact.key}`，渲染时替换。
区别是报告里写了不存在的 key 会被打回重写，这里只有 render_text(strict=False)
兜着 —— 对话是线性的，没有 repair 环，也没有必要为一句闲聊重跑 30 秒。
"""

from __future__ import annotations

import json

from musicmind_agent.evidence import SCOPE_ALL
from musicmind_agent.llm import LLMClient
from musicmind_agent.render import render_text
from musicmind_agent.tools import build_context, call, catalog

# 一轮最多查几个工具。一口气全跑完就没有「根据上一轮结果决定下一轮」了
MAX_TOOLS_PER_ROUND = 3
# 一共几轮。比 ask 的 3 轮宽 —— 对话要查的可能是多步的
MAX_CHAT_ROUNDS = 6
# 带几轮历史进 prompt。留太多会把工具目录和事实挤到窗口边缘
HISTORY_TURNS = 6
# 一轮回答最多推几首
MAX_RECO = 10
# 一次最多提议抓几张。和 Java 那边的 MAX_BATCH 对齐
MAX_FETCH_PROPOSALS = 5


CHAT_SYSTEM = """你在帮用户探索他自己的音乐库。

硬规则：

1. **只能用工具查出来的事实回答。** 不许凭印象说「你喜欢的应该是……」。
   工具没查到的就不要说。

2. 要提数字就写占位符 `{事实的key}`，渲染时替换成真值。自己编数字 = 回答作废。

   **占位符会连单位一起渲染出来**：`share`/`ratio` 渲染成 `68.3%`，
   `lift` 渲染成 `2.3 倍`。所以写「占 {key}」不要写成「占 {key} %」，
   写「是基准的 {key}」不要写成「是基准的 {key} 倍」—— 会变成「2.3 倍 倍」。

3. **只能引用「可以引用的事实」里出现过的键，一个字母都不能改。**
   没有的键就是不存在，不要按命名规律拼。

4. 数据回答不了就直说「这套数据回答不了」。**不要用常识或者对歌手的印象凑答案。**

5. 说话像一个懂音乐的朋友，用「你」，不要用「用户」。
   简短，2-5 句。用户是随口问一句，不是在看论文。

6. **库里没有的东西，「推荐」和「常识」分开处理：**

   · **推荐列表里一条都不能出现库外的歌。** 推荐是**断言**（「这首适合你」），
     而库外的歌查不到流派/年代/能量，撑不起这个断言 —— 硬凑就是「我觉得好听」。
     `candidate_index` 只能从「候选曲目」那张表里选。

   · **常识性问题如实说答不了。** 用户问「Radiohead 是什么风格」，
     库里没有他的歌，就说「我的库里没有 Radiohead 的歌，这个问题我答不了」。
     **不要说「据我所知……」。** 那句话引进了一个没有来源的断言，
     而这个系统里每句话都要能指回一条事实 —— 一旦开口子，
     它就再也不会说「答不了」了。

   · **但「库里没有」不等于「到此为止」。先调 `search_upstream` 找一找再回答。**
     上游可能有，找到了就填进 `fetch_proposals` 问用户要不要抓。

     【为什么必须专门写这一条】实测踩过：用户说「给我推荐林俊杰的歌曲」，
     模型查了事实表发现没有林俊杰，直接回了一句「这件事我做不到」就收工了 ——
     **一个工具都没调**（`used_tools` 是空的）。它没做错什么，
     只是没人告诉它「库里没有的东西可以去上游找」。
     光有 `search_upstream` 这个工具不够，得在规则里明确要求它去用。

     注意范围：只在用户**要某个我们库里没有的东西**（某歌手、某流派、某张专辑）时去找。
     查用户自己的数据（「我最常听什么」）不用找上游。
    
   . **问「是什么」「为什么」「有什么背景」这类知识和背景问题，用 `search_knowledge` 查语料。**
     比如「Britpop 是什么」「Oasis 和 Blur 为什么总被放在一起」。
     这些不在你的数据里，在语料里 —— **不要凭印象答，去查**。
     
     语料说的是音乐知识，不是用户的听歌记录。查回来的内容可以直接讲，
     但它**不是用户的歌**，不能拿它说「你听过……」。

   两条的区别是**主张的强度**：推荐是替你判断，常识只是转述。
   系统只敢做前者里可验证的那部分。

输出 JSON，两种形式之一：

要查东西（一轮最多 3 个）：
{"calls": [{"tool": "工具名", "args": {"参数": "值"}}]}

直接回答：
{"answer": "回答，数字写 {fact.key}", "recommendations": [{"candidate_index": 3, "reason": "为什么推它"}], "fetch_proposals": [{"release_mbid": "照抄 search_upstream 返回的", "why": "为什么建议抓这张"}]}

**fetch_proposals 只在「用户问的东西库里没有、而 search_upstream 找到了候选」时填**，
最多 5 条。`release_mbid` 只能照抄工具返回的，**不要自己编** —— 编出来的 id
要么不存在，要么是另一张专辑，而抓取会照着它去抓。

**你不能自己抓，也不能假设已经抓了。** 抓取是异步的（要 30-60 秒），
而且必须用户点了才会发生 —— 回答里问他一句「要我抓进来吗」就够了。

**recommendations 只在用户明确要推荐、而且你确实调过工具拿到候选时才填**，
最多 10 条。`candidate_index` 只能从「候选曲目」那张表里选，不要自己编序号。
不推就写空数组。
"""


CHAT_USER = """## 可以引用的事实（**只能引用这张表里出现过的键**）

{facts}

## 候选曲目（要推荐就从这里选序号）

{candidates}

**它们【不是】用户听过的歌，是工具查出来的备选。**
不要拿它们当「你已经有了」的依据。空的时候说明还没查过 —— 那就先调工具。

## 你手里有哪些工具

{catalog}

## 最近聊过的

{history}

## 用户现在问

{question}
"""


# ============================================================
# 候选池：模型只看得见序号，看不见真 track_id
# ============================================================

class CandidatePool:
    """这一轮对话里出现过的备选曲目。

    【为什么不给模型真 track_id】报告那边踩过一次：prompt 里同时出现两列 id
    （evidence 里用户听过的 + 候选里没听过的），模型分不清，把候选 id 当证据写，
    实测 10 次跑有 10 次因此触发 repair。这里干脆不给 —— 它只能写序号，
    序号到 id 的映射在外面做。

    ```python
    pool = CandidatePool()
    idx = pool.add({"track_id": 8123, "歌名": "十年"})   # → 1
    pool.resolve(1)["track_id"]                          # → 8123
    ```
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}

    def add(self, row: dict) -> int:
        """同一首歌重复出现时复用原来的序号 —— 不然同一首会占好几个号。"""
        for idx, existing in self._by_index.items():
            if existing.get("track_id") == row.get("track_id"):
                return idx
        idx = len(self._by_index) + 1
        self._by_index[idx] = row
        return idx

    def numbered(self) -> list[dict]:
        return [
            {"candidate_index": i, **{k: v for k, v in row.items() if k != "track_id"}}
            for i, row in sorted(self._by_index.items())
        ]

    def resolve(self, index) -> dict | None:
        return self._by_index.get(index)



def _number_rows(rows, pool: CandidatePool) -> list:
    """把工具行里的 track_id 换成一个全局序号。

    没有 track_id 的行（coverage、聚合类）原样留下 —— 它们本来就没 id 可藏。
    """
    out = []
    for row in rows or []:
        if isinstance(row, dict) and row.get("track_id") is not None:
            out.append({
                "candidate_index": pool.add(row),
                **{k: v for k, v in row.items() if k != "track_id"},
            })
        else:
            out.append(row)
    return out


# ============================================================
# 拼上下文
# ============================================================

def _overview(ctx) -> dict:
    """给模型看的事实表。

    **只给 key 和值，不给原始行** —— 119 条已经够长了，再塞 rows 会把
    工具目录和历史挤出去。
    """
    return {k: v for k, v in sorted(ctx.facts.items())}


def _format_history(history: list[dict]) -> str:
    if not history:
        return "（这是第一句）"
    lines = []
    for msg in history[-HISTORY_TURNS * 2:]:
        who = "你" if msg["role"] == "assistant" else "用户"
        lines.append(f"{who}：{_text_of(msg['content'])}")
    return "\n".join(lines)


def _text_of(content: str) -> str:
    """会话里的 assistant 消息是 JSON，历史里只取 answer 那一句。

    整份 JSON 塞进历史没有意义 —— recommendations 里那十条理由会白占几百 token。
    """
    if not content or not content.lstrip().startswith("{"):
        return content
    try:
        return json.loads(content).get("answer") or content
    except json.JSONDecodeError:
        return content


def _format_result(name: str, data: dict, pool: CandidatePool) -> str:
    """一个工具的输出，拼成给模型看的一段。**和报告那边同一个形状**。"""
    blocks = [f"### {name}"]
    if data.get("facts"):
        blocks.append(f"facts: {json.dumps(data['facts'], ensure_ascii=False)}")

    rows = _number_rows(data.get("rows"), pool)
    if rows:
        blocks.append(f"rows: {json.dumps(rows[:15], ensure_ascii=False)}")

    # 【evidence 必须给】它列的是【用户自己的曲目】，是唯一可以拿来当证据的 id 池
    evidence = data.get("evidence")
    if evidence:
        blocks.append("evidence（这些是【用户自己听过的曲目】）: "
                      + json.dumps(evidence[:10], ensure_ascii=False))

    if data.get("coverage"):
        blocks.append(f"coverage: {json.dumps(data['coverage'], ensure_ascii=False)}")

    # 【warning 要转达】工具出异常会被 call() 兜成空结果 + warning。
    # 不说的话模型看到一行空数据，会以为「库里没有」，而实际是工具挂了
    if data.get("warnings"):
        blocks.append(f"warnings: {data['warnings']}")

    return "\n".join(blocks)


# ============================================================
# 主循环
# ============================================================

def chat(connection, user_id: int, message: str,
         history: list[dict], provider: str) -> dict:
    """跑一轮对话。返回 {answer, recommendations, used_tools}。"""

    ctx = build_context(connection, user_id, None, SCOPE_ALL, None)
    client = LLMClient(provider=provider)
    pool = CandidatePool()
    used: list[str] = []
    # search_upstream 返回的候选。它们没有 track_id（不在库里），
    # 所以 _number_rows 不会碰它们 —— 单独留一份给 fetch_proposals 用
    upstream_rows: list[dict] = []

    # 【必须先跑一遍核心工具】build_context 只把曲目装进 ctx，**不填 facts 仓**。
    # 报告那条路靠上一步的 compose 填过了，对话没有上一步 ——
    # 不跑的话模型面前一张事实表都没有，只能凭印象说话。
    from musicmind_agent.tools import core_tool_names
    for name in core_tool_names():
        call(name, ctx)

    messages = [
        {"role": "system", "content": CHAT_SYSTEM},
        {"role": "user", "content": CHAT_USER.format(
            facts=json.dumps(_overview(ctx), ensure_ascii=False, indent=1),
            candidates="（还没有候选。要推荐就先调工具查）",
            catalog=json.dumps(catalog(), ensure_ascii=False, indent=1),
            history=_format_history(history),
            question=message,
        )},
    ]

    allowed = {t["name"] for t in catalog()}

    for _round in range(MAX_CHAT_ROUNDS):
        raw, _resp = client.chat_json(messages)

        calls = raw.get("calls") or []
        if calls:
            blocks = []
            for req in calls[:MAX_TOOLS_PER_ROUND]:
                name = req.get("tool")
                if name not in allowed:
                    # 编的工具名：告诉它一次，不当错误 —— 它只是少查了一样东西
                    blocks.append(f"### {name}\n（没有这个工具，可选的在目录里）")
                    continue
                result = call(name, ctx, req.get("args") or {})
                used.append(name)
                if name == "search_upstream":
                    upstream_rows.extend(result.rows)
                blocks.append(_format_result(name, result.as_dict(), pool))

            messages.append({"role": "assistant",
                             "content": json.dumps(raw, ensure_ascii=False)})
            # 【每轮都要重发候选表】模型上一轮选的序号这一轮还得能用
            messages.append({"role": "user", "content":
                             "## 工具结果\n" + "\n\n".join(blocks)
                             + "\n\n## 现在手上的候选（序号是全局的，可以跨轮引用）\n"
                             + json.dumps(pool.numbered()[:30], ensure_ascii=False)
                             + "\n\n现在给出回答。"})
            continue

        text = raw.get("answer")
        if text:
            return {
                "answer": render_text(text, ctx.facts, strict=False),
                "recommendations": _resolve_recos(raw.get("recommendations"), pool, ctx),
                "fetch_proposals": _resolve_proposals(raw.get("fetch_proposals"), upstream_rows, ctx),
                "used_tools": used,
            }

    return {"answer": "这个问题我查了几轮都没凑齐能回答的数据。",
            "recommendations": [], "fetch_proposals": [], "used_tools": used}


def _resolve_proposals(items, upstream_rows: list[dict], ctx) -> list[dict]:
    """把模型提议的 release 映射回 search_upstream 真返回过的那几条。

    **和推荐同一条规矩：只认工具真的返回过的 mbid。** 模型见过一堆 uuid，
    会照着格式编一个 —— 而抓取会照着它去抓，结果要么 404，要么抓到另一张专辑，
    而且失败要等几分钟才看得到。越界的直接丢，不猜。
    """
    by_mbid = {r["release_mbid"]: r for r in upstream_rows}
    out = []
    for item in (items or [])[:MAX_FETCH_PROPOSALS]:
        row = by_mbid.get((item or {}).get("release_mbid"))
        if row is None:
            continue
        # 【why 也要渲染】和 recommendations 的 reason 同一条规矩：
        # 凡是 LLM 写的文本都要过一遍 render_text，没有例外。
        # 漏了的话用户看到的是「正好落在你库里 2005-2010 那两段（合计占 {era.2005.share}）」
        out.append({**row,
                    "why": render_text(item.get("why") or "", ctx.facts, strict=False)})
    return out


def _resolve_recos(items, pool: CandidatePool, ctx) -> list[dict]:
    """把模型给的序号映射回真 track_id。

    **越界的序号直接丢掉，不猜。** 猜错了推的是另一首歌，而且没人会发现。
    和 `graph/nodes.py::_map_candidates` 同一条规矩。
    """
    out = []
    for item in (items or [])[:MAX_RECO]:
        idx = item.get("candidate_index")
        row = pool.resolve(idx) if isinstance(idx, int) else None
        if row is None:
            continue
        out.append({
            "track_id": row["track_id"],
            "name": row.get("歌名"),
            "artist_names": row.get("艺人"),
            "album_name": row.get("专辑"),
            "reason": render_text(item.get("reason") or "", ctx.facts, strict=False),
        })
    return out


# ============================================================
# 落库
# ============================================================

def _load_history(connection, conversation_id: int) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT role, content FROM agent_message "
            "WHERE conversation_id = %s ORDER BY id", (conversation_id,))
        return list(cursor.fetchall())


def chat_and_persist(connection, run_id: int) -> None:
    """从 agent_run 领一条 chat 任务，跑，写回消息。"""

    from musicmind_agent.persist import load_run

    run = load_run(connection, run_id)
    if run is None:
        # 【抛，不能静默 return】静默返回的话 cli 照打 CHAT_OK 退出码 0，
        # Java 认为成功、不做兜底，那条 run 永远停在 RUNNING
        raise RuntimeError(f"agent_run 里没有 id={run_id} 的行，什么都没跑")

    conversation_id = run.get("conversation_id")
    if conversation_id is None:
        raise RuntimeError(f"run {run_id} 上没有 conversation_id，这不是一条对话任务")

    history = _load_history(connection, conversation_id)

    result = chat(connection, run["user_id"], run["question"], history, run["provider"])

    with connection.cursor() as cursor:
        # 先记用户那句，再记回答 —— 顺序就是 UI 里的显示顺序
        cursor.execute(
            "INSERT INTO agent_message (conversation_id, run_id, role, content) "
            "VALUES (%s,%s,'user',%s)",
            (conversation_id, run_id, run["question"]))
        cursor.execute(
            "INSERT INTO agent_message (conversation_id, run_id, role, content) "
            "VALUES (%s,%s,'assistant',%s)",
            (conversation_id, run_id, json.dumps(result, ensure_ascii=False)))
        cursor.execute(
            "UPDATE agent_run SET status='DONE', finished_at=NOW() WHERE id=%s", (run_id,))
    connection.commit()