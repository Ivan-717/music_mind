# M2 交接：对话入口

**这一步的 Python 部分是你写，我验收。** 目标：用户能用自然语言问，Agent 查工具、回答，
必要时给推荐。这是 project.md §3.1 那五条用户目标里 ①②⑤ 缺的那块**骨架**。

对应的路线图在 `~/.claude/plans/project-md-mighty-hopcroft.md` 的 M2。

---

## 起点：**这不是从零造 Agent**

`ask.py`（追问）已经是一个完整的工具循环了，难的部分全做完了：

```
build_context → LLM（带工具目录）→ 挑工具 → 白名单校验 → 结果回灌 → 回答 → 渲染数字
```

这一步是**把它泛化**。两处不同：

| | ask（已有） | chat（要建） |
|---|---|---|
| 上下文 | 某份报告的 facts 快照 | **现算**的用户画像 |
| 轮数 | 3 | 6 |
| 输出 | 一段答案 | 答案 + **推荐列表** |
| 历史 | 那张报告的全部消息 | 这个会话的最近 6 轮 |

**不用动**：`graph/`（图是 report 专用的，chat 和 ask 一样走普通函数循环）、
`validate/`、`render.py`、`tools/` 的 15 个工具、`AgentWorker` 子进程协议。

---

## 要建的东西

```
agent-service/
  schema-agent.sql                     ← 1. 三处 schema 改动（我执行）
  musicmind_agent/chat.py              ← 2. 【你写】完整代码见下
  musicmind_agent/cli.py               ← 3. 【你写】加一个 chat 子命令

backend/  frontend/                    ← 4. 我接（你不用管，见最后一节）
```

---

## 1. schema（我来执行，你只要知道有这几列）

```sql
-- 新表：一个会话
CREATE TABLE IF NOT EXISTS `agent_conversation` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '新的对话',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_conv_user` (`user_id`,`id`),
  CONSTRAINT `fk_conv_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 队列行要知道自己属于哪个会话
ALTER TABLE `agent_run`
  ADD COLUMN `conversation_id` bigint unsigned DEFAULT NULL AFTER `report_id`;

-- 消息：追问挂 report_id，对话挂 conversation_id，两者互斥
ALTER TABLE `agent_message`
  MODIFY `report_id` bigint unsigned DEFAULT NULL,
  ADD COLUMN `conversation_id` bigint unsigned DEFAULT NULL AFTER `report_id`,
  ADD KEY `idx_msg_conv` (`conversation_id`,`id`);
```

**`content` 这一列有两种形状**，靠挂在哪张表上区分：

```
挂 report_id      → 纯文本（追问的回答，原有行为）
挂 conversation_id → JSON：{"answer": "...", "recommendations": [...]}
```

前端按会话类型解析。**旧数据（追问）一条不动。**

---

## 2. `musicmind_agent/chat.py` —— 完整代码

```python
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

   两条的区别是**主张的强度**：推荐是替你判断，常识只是转述。
   系统只敢做前者里可验证的那部分。

输出 JSON，两种形式之一：

要查东西（一轮最多 3 个）：
{"calls": [{"tool": "工具名", "args": {"参数": "值"}}]}

直接回答：
{"answer": "回答，数字写 {fact.key}", "recommendations": [{"candidate_index": 3, "reason": "为什么推它"}]}

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
                "used_tools": used,
            }

    return {"answer": "这个问题我查了几轮都没凑齐能回答的数据。",
            "recommendations": [], "used_tools": used}


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
```

---

## 3. `cli.py` 加子命令

照抄 `cmd_ask`，三处：

```python
def cmd_chat(args: argparse.Namespace) -> int:
    """跑一轮对话并落库。Java 子进程调的就是这个。"""
    from musicmind_agent.chat import chat_and_persist
    from musicmind_agent.persist import mark_failed

    connection = get_connection()
    try:
        chat_and_persist(connection, args.run_id)
    except Exception as e:
        try:
            mark_failed(connection, args.run_id, f"{type(e).__name__}: {e}")
        except Exception:
            pass
        print(f"CHAT_FAIL {args.run_id} {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        connection.close()

    print(f"CHAT_OK {args.run_id}")
    return 0
```

`main()` 里：

```python
    p_chat = sub.add_parser("chat", help="跑一轮对话（Java 子进程调用）")
    p_chat.add_argument("--run-id", type=int, required=True)
    p_chat.set_defaults(func=cmd_chat)
```

---

## 4. 先自己跑通再碰 Java

```bash
cd agent-service

# 手工建会话 + 排一条 chat run
.venv/Scripts/python.exe -c "
import sys; sys.stdout.reconfigure(encoding='utf-8')
from musicmind_agent.db import get_connection
c = get_connection(); cur = c.cursor()
cur.execute(\"INSERT INTO agent_conversation (user_id, title) VALUES (34, '测试')\")
conv = cur.lastrowid
cur.execute(\"INSERT INTO agent_run (user_id, kind, question, provider, conversation_id, scope_kind) \"
            \"VALUES (34, 'chat', '我听得最多的是什么流派？', 'deepseek', %s, 'all')\", (conv,))
print('conversation_id =', conv, ' run_id =', cur.lastrowid)
c.commit(); c.close()"

# 跑
.venv/Scripts/python.exe -m musicmind_agent.cli chat --run-id <上面那个 run_id>

# 看消息有没有落
.venv/Scripts/python.exe -c "
import sys; sys.stdout.reconfigure(encoding='utf-8')
from musicmind_agent.db import get_connection
c = get_connection(); cur = c.cursor()
cur.execute('SELECT role, LEFT(content,200) FROM agent_message WHERE conversation_id=%s ORDER BY id', (<conv>,))
for r in cur.fetchall(): print(r)
c.close()"
```

**换几个问题试**：

```
「我听得最多的是什么流派？」        → 数字要和人格报告对得上
「推荐几首安静的」                  → 要给 recommendations，每条带理由
「我听过 Radiohead 吗？」           → 要如实说没有（库里确实 0 首）
```

---

## 验收标准

1. 问「我听得最多的是什么流派」→ 回答里的数字**和人格报告一致**（同一个 facts 仓）
2. 问「推荐几首安静的」→ 给出推荐，每首有理由，`track_id` **真实存在于库里**
3. **连续问 3 轮** → 第 3 轮还记得第 1 轮说了什么（多轮上下文生效）
4. **库里没有的**（两个都要测）：
   - 「推荐几首 Radiohead 的歌」→ 推荐列表**必须是空的**，并说明库里没有
   - 「Radiohead 是什么风格」→ 如实说这个答不了，**不能出现「据我所知」这类
     没有来源的话**

   这一条最重要。它测的不是模型知不知道 Radiohead（它当然知道），
   而是它**肯不肯承认这个系统不知道**
5. 回答里**没有未渲染的 `{占位符}`**
6. run 失败时 `agent_run.status = 'FAILED'` 且 `error_message` 有内容

---

## 七个坑

1. **`build_context` 不填 facts 仓。** 必须先 `for name in core_tool_names(): call(name, ctx)`，
   否则模型面前一张事实表都没有 —— 这是最容易漏的一步（`ask.py` 靠报告的快照绕过了它）
2. **别把真 `track_id` 给模型。** 报告那边实测 10 次跑有 10 次因为它触发 repair。
   `CandidatePool` 就是为了这个
3. **每轮重发候选表。** 上一轮选的序号这一轮还得能用，否则模型会重新编一个
4. **工具的 warning 要转达给模型。** `call()` 会把异常兜成空结果 + warning，
   不转达的话「工具挂了」看起来和「库里没有」一模一样
5. **失败必须写回 run 行。** 否则队列里那条永远停在 RUNNING，前端一直转圈

6. **「库外推荐」有机械防线，「据我所知」没有。** 前者是结构上堵死的 ——
   序号映射不到候选池就丢掉（`_resolve_recos`），模型写不出库外的推荐。
   后者**只能靠 prompt 和验收时人工看**，别指望测试拦住它。
   这也是为什么第 4 条验收要人眼看，而不是断言一个字符串不存在
   （用「据我所知」当关键词去堵是堵不完的，换个说法就绕过去了）

7. **system prompt 里一个字的「写给开发者的话」都不能留。** 真的踩了：
   第 6 条原本末尾写了一句「等语料接上（M6）再改这条」—— 那是给我自己看的备注，
   结果模型在回答里原样输出：「我库里没有 Radiohead 的歌……**等语料接上再说吧**」。
   用户看到的是一句莫名其妙的话，而且它暴露了内部路线图。

   prompt 是**模型的输入**，不是代码注释。所有「这条以后要改」「这样做是因为
   当年踩过坑」的话，都要写在函数的 docstring 或代码注释里。
   验收时留意回答里有没有出现 M1/M2/语料/评估这类**只存在于开发语境**的词。

---

## 我这边接的（你不用管）

- schema 的三处改动（我执行并验证）
- `AgentService.chat()` + `AgentController` 的三个端点 + `AgentRun` 实体加一列
- `ExploreView.vue` + `api/chat.js` + 路由 + 导航
- 端到端脚本 `scripts/test_chat.py`（越权、多轮、失败可见）

**写完发我**：跑通的三个问题 + 各自的回答（尤其是第 4 条「库里没有的」那个）。
