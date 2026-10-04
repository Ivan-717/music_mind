# Phase 6 交接：Java 接入 + 落库 + 追问 + 前端

**这一步是你写，我验收。** 目标：让用户在网页上点一下就能看到音乐人格报告，
并且能对着报告追问。

```bash
# 后端
mvn -f backend spring-boot:run
# 前端
cd frontend && npm run dev
# 打开 http://localhost:5173/persona
```

---

## 起点：先看清楚有三块空白

我查过了，**不是「接根线」那么简单**：

```
1. 追问的图逻辑   ⬜ 完全没有 —— state 里有 mode: ask，但图里没有对应节点
2. Agent 侧的表   ⬜ 一张都没建 —— schema-agent.sql 里只有音频特征那两张
3. Java + 前端    ⬜ 完全没有
```

工作量大概是 Phase 4/5 的量级，不是 Phase 2 那种。

---

## 已经验证过的事实（直接用，别重新试）

**① 一次报告要 30 秒 → 必须异步**

```
deepseek  p50 = 28.7s   p95 = 33.2s   min=15.5s  max=48.3s
千问      单步 compose 就要 62s，整轮更久
```

前端 axios 默认 timeout 是 10 秒。**同步接口必然超时**，所以走 **202 + 轮询**。
形状和 `ingestion_job` 那套完全一样（表 + 单线程 worker + 前端 3 秒轮询），
那套已经跑了几百条任务，直接照抄。

**② Python 侧的入口已经有了**

```bash
.venv/Scripts/python.exe -m musicmind_agent.cli agent --user 34 --provider deepseek --out out/run-1
```

输出：
```
降级：False   修复轮次：1   探针：1   LLM 调用：5
tokens in=13008 out=3753

  resolve_user          0ms  448 首 / 98 位艺人
  plan               1440ms  选了 [...]
  run_core_tools        1ms  6 个核心工具，facts 仓 119 条
  probe               829ms  模型认为够了
  compose           14032ms
  validate             30ms  检查 222 处，警告 1
  persist               0ms  out/run-1
```

**③ 子进程的约定照抄 `IngestionWorker`**（那个仓库里已经踩过所有坑）：

```java
ProcessBuilder builder = new ProcessBuilder(python, "-m", "musicmind_agent.cli",
                                            "run", "--run-id", String.valueOf(runId));
builder.directory(new File(props.getAgentServiceDir()));
builder.redirectErrorStream(true);          // ← 必须合并，否则管道写满假死
builder.redirectOutput(ProcessBuilder.Redirect.appendTo(logFile.toFile()));
builder.environment().put("PYTHONIOENCODING", "utf-8");   // ← Windows GBK 会炸
```

**④ 「Python 写、Java 读」这条边界不能破**

`agent_report` / `agent_run` / `agent_message` 三张表**归 agent-service 写**，
Spring Boot 只读。见 `schema-user.sql` 头注释里那三条归属规则，Agent 侧是第三条。

**Java 端不许解析报告的 JSON 内部结构** —— 拿到什么原样透传给前端。
一旦 Java 里出现了 `reportJson.get("dimensions")` 这种代码，报告 schema 一改
就要两边同时改，而那种 bug 会在生产上才现形。

---

## 要建的东西

```
agent-service/
  schema-agent.sql                     ← 1. 加三张表
  musicmind_agent/
    cli.py                             ← 2. 加 run / ask 两个子命令（写库版）
    persist.py                         ← 3. 把报告写进 agent_report
    ask.py                             ← 4. 追问（图里最缺的那块）

backend/src/main/java/com/musicmind/
  config/AgentProperties.java          ← 5. 照 IngestionProperties 的形
  mapper/AgentRunMapper.java           ← 6. 照 IngestionJobMapper 的形
  service/AgentWorker.java             ← 7. 照 IngestionWorker 的形
  service/AgentService.java            ← 8.
  controller/AgentController.java      ← 9.
  resources/application.yaml           ← 10. 加 agent: 节

frontend/src/
  api/persona.js                       ← 11.
  views/PersonaView.vue                ← 12.
  router/index.js  +  App.vue          ← 13. 各一行
```

---

## 1. `schema-agent.sql` 追加三张表

```sql
-- ============================================================
-- 报告
-- ============================================================

CREATE TABLE IF NOT EXISTS `agent_report` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `status` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'ok'
      COMMENT 'ok / degraded / insufficient_data',

  -- 【报告主体存 JSON 列，不拆表】schema 还会快速演化（Phase 7 要加维度），
  -- 拆成 claim 明细表的话每加一个字段都要迁移。库里有先例：album.secondary_types
  `report_json` json NOT NULL COMMENT '渲染后的完整报告',
  `facts_json` json DEFAULT NULL COMMENT '本轮的事实仓快照，追问时要用',
  `data_scope_json` json DEFAULT NULL COMMENT '规模与覆盖率，前端直接显示',

  `headline` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '标题，列表页用',
  `llm_provider` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `llm_model` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `prompt_version` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `tokens_in` int unsigned DEFAULT NULL,
  `tokens_out` int unsigned DEFAULT NULL,
  `latency_ms` int unsigned DEFAULT NULL,

  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_report_user` (`user_id`,`id`),
  CONSTRAINT `fk_report_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='音乐人格报告（agent-service 写，Spring Boot 只读）';

-- ============================================================
-- 运行队列（形状照抄 ingestion_job）
-- ============================================================

CREATE TABLE IF NOT EXISTS `agent_run` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `kind` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'report'
      COMMENT 'report / ask',
  `question` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'ask 模式的问题',
  `report_id` bigint unsigned DEFAULT NULL COMMENT 'ask 模式针对哪份报告；也用于 report 完成后回填',
  `provider` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,

  `status` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'QUEUED'
      COMMENT 'QUEUED / RUNNING / DONE / FAILED',
  `error_message` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `started_at` timestamp NULL DEFAULT NULL,
  `finished_at` timestamp NULL DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  KEY `idx_run_status` (`status`,`id`),
  KEY `idx_run_user` (`user_id`,`id`),
  CONSTRAINT `fk_run_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Agent 运行队列（单 worker 顺序消费）';

-- ============================================================
-- 追问的消息
-- ============================================================

CREATE TABLE IF NOT EXISTS `agent_message` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `report_id` bigint unsigned NOT NULL,
  `run_id` bigint unsigned DEFAULT NULL,
  `role` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'user / assistant',
  `content` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_msg_report` (`report_id`,`id`),
  CONSTRAINT `fk_msg_report` FOREIGN KEY (`report_id`)
    REFERENCES `agent_report` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='追问的消息。**UI 的数据源是这张表** —— LangGraph 的 checkpoint 是库内部格式，不能当 UI 数据源';
```

**执行 DDL**（用 python 跑，和之前一样）：

```bash
cd agent-service
.venv/Scripts/python.exe -c "
import re, pymysql
from musicmind_agent.config import MYSQL_CONFIG
sql = open('schema-agent.sql', encoding='utf-8').read()
conn = pymysql.connect(**{**MYSQL_CONFIG, 'autocommit': True}); cur = conn.cursor()
for stmt in re.findall(r'^CREATE TABLE IF NOT EXISTS.*?;', sql, re.S | re.M):
    cur.execute(stmt); print('OK', re.search(r'\`(\w+)\`', stmt).group(1))
conn.close()"
```

---

## 2. `cli.py` 加两个子命令

**`run`（写库版，Java 子进程调的）**

```python
def cmd_run(args) -> int:
    """跑一次报告并落库。Java 子进程调这个。

    【为什么要有它，而不是直接调 agent 子命令】
    `agent` 把报告写文件、退出码表意，那是开发和调试用的。
    Java 需要的是「扔一个 run-id 进去，结果自己落库」——
    因为写库是 agent-service 的职责（见 schema-user.sql 的归属规则），
    Java 那边不该碰 agent_report。
    """
    from musicmind_agent.persist import run_and_persist

    connection = get_connection()
    try:
        run_and_persist(connection, args.run_id)
    except Exception as e:
        # 【失败也要写回 run 行】否则队列里那条永远停在 RUNNING
        from musicmind_agent.persist import mark_failed
        mark_failed(connection, args.run_id, f"{type(e).__name__}: {e}")
        print(f"RUN_FAIL {args.run_id} {e}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(f"RUN_OK {args.run_id}")
    return 0
```

**`ask`（追问，同样写库）**

```python
def cmd_ask(args) -> int:
    from musicmind_agent.ask import answer_and_persist

    connection = get_connection()
    try:
        answer_and_persist(connection, args.run_id)
    except Exception as e:
        from musicmind_agent.persist import mark_failed
        mark_failed(connection, args.run_id, f"{type(e).__name__}: {e}")
        print(f"ASK_FAIL {args.run_id} {e}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    print(f"ASK_OK {args.run_id}")
    return 0
```

`main()` 里加：

```python
    p_run = sub.add_parser("run", help="跑一次报告并落库（Java 子进程调用）")
    p_run.add_argument("--run-id", type=int, required=True)
    p_run.set_defaults(func=cmd_run)

    p_ask = sub.add_parser("ask", help="对一份报告追问（Java 子进程调用）")
    p_ask.add_argument("--run-id", type=int, required=True)
    p_ask.set_defaults(func=cmd_ask)
```

---

## 3. `musicmind_agent/persist.py`

```python
"""把报告写进 agent_report，并更新 agent_run 的状态。

【这个文件存在的唯一理由】`agent_service` 是 agent 侧表的唯一写者。
Java 只建 run 行（QUEUED 状态也算「排队信息」）、只读报告，
它不解析也不写报告内容 —— 一旦 Java 开始写 report_json，
schema 一改就要两边同时改。
"""

from __future__ import annotations

import json
import time
from functools import partial

from musicmind_agent.db import get_connection
from musicmind_agent.evidence import EnrichedTrack
from musicmind_agent.graph import run_report


def _row(connection, sql: str, args: tuple):
    with connection.cursor() as cursor:
        cursor.execute(sql, args)
        return cursor.fetchone()


def claim_run(connection, run_id: int) -> dict | None:
    """把一条 QUEUED 的 run 领走。返回 None = 没抢到（已经被处理或不存在）。

    WHERE 带 status='QUEUED' —— 和 ingestion_job 那边同一个道理：
    UPDATE 的返回值在有 useAffectedRows=false 时不可靠，条件本身才是互斥。
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_run SET status='RUNNING', started_at=NOW() "
            "WHERE id=%s AND status='QUEUED'", (run_id,))
        if cursor.rowcount == 0:
            return None
    return _row(connection, "SELECT * FROM agent_run WHERE id=%s", (run_id,))


def mark_failed(connection, run_id: int, message: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_run SET status='FAILED', error_message=%s, finished_at=NOW() "
            "WHERE id=%s", (message[:1000], run_id))


def run_and_persist(connection, run_id: int) -> int:
    """跑一次报告，落库，回填 run 行。返回 report_id。"""
    run = claim_run(connection, run_id)
    if run is None:
        return 0

    started = time.monotonic()
    final = run_report(connection, run["user_id"], run["provider"],
                       out_dir=None, reco_count=RECO_COUNT)

    rendered = final.get("rendered") or {}
    facts = final.get("facts") or {}
    usage = final.get("usage") or {}

    status = "insufficient_data" if usage.get("insufficient") else (
        "degraded" if final.get("degraded") else "ok")

    data_scope = {k: v for k, v in facts.items()
                  if k.startswith(("scope.", "coverage.", "mood.measured",
                                   "mood.inferred"))}

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO agent_report
                (user_id, status, report_json, facts_json, data_scope_json, headline,
                 llm_provider, llm_model, tokens_in, tokens_out, latency_ms)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (run["user_id"], status,
             json.dumps(rendered, ensure_ascii=False),
             json.dumps(facts, ensure_ascii=False, default=str),
             json.dumps(data_scope, ensure_ascii=False, default=str),
             (rendered.get("headline") or {}).get("title"),
             usage.get("provider"), usage.get("model"),
             usage.get("tokens_in"), usage.get("tokens_out"),
             int((time.monotonic() - started) * 1000)))
        report_id = cursor.lastrowid

        cursor.execute(
            "UPDATE agent_run SET status='DONE', report_id=%s, finished_at=NOW() WHERE id=%s",
            (report_id, run_id))
    connection.commit()
    return report_id


# 【推荐条数】产品上没人读 50 条；技术上 50 条的输出会把 max_tokens 撑爆
# （实测 8192 都在边界上，一半的折 JSON 被截断）。20 条是稳的。
RECO_COUNT = 20
```

---

## 4. `musicmind_agent/ask.py` —— **图里最缺的那块**

追问不重跑整个图。它做三件事：读报告上下文 → 工具循环 → 写回消息。

```python
"""对一份已生成的报告追问。

【为什么不复用 compose 那张图】那张图是「从零生成一份报告」的流程：
plan → 探针 → compose → validate → repair。追问只需要「带着上下文答案」，
重跑一遍是浪费（30 秒 + 一次完整 LLM 开销）。

【上下文从哪来】报告 JSON 的压缩版 + facts 仓快照（都存在 agent_report 里）。
**不是从 LangGraph 的 checkpoint 读** —— 那是库内部格式，换个版本就不能读了。
追问的历史从 agent_message 表重建，那本来就是 UI 的数据源。
"""

from __future__ import annotations

import json

from musicmind_agent.llm import LLMClient
from musicmind_agent.tools import build_context, call, catalog
from musicmind_agent.tools.base import ToolContext

ASK_SYSTEM = """你在回答用户对自己音乐人格报告的追问。

规则：

1. **只能用工具查出来的事实回答**。不许凭印象说「你喜欢的应该是……」。
   报告里的数字来自「用户数据概览」，工具返回的 facts 也是同一套。

2. 要提数字就写占位符 `{事实的key}`，渲染时替换。自己编数字 = 作废。

3. 每句话都要能指回数据。做不到就直说「这套数据回答不了」。

4. 回答简短，2-4 句。用户是在看报告时顺手问一句，不是要一篇论文。
"""

ASK_USER = """## 报告（已经渲染过的）

{report}

## 用户数据概览（可以引用的事实）

{facts}

## 用户的追问

{question}

输出 JSON：{{"answer": "回答，数字写 {{fact.key}}", "used_tools": ["用过的工具名"]}}
"""

MAX_ASK_TOOLS = 4


def answer(connection, user_id: int, report: dict, facts: dict,
           question: str, provider: str) -> str:
    """回答一个问题。返回渲染后的回答文本。"""

    # 追问时用全部 13 个工具 —— 报告生成时只给探针是因为要控制不确定性，
    # 追问是用户在主导，给他最全的能力
    ctx: ToolContext = build_context(connection, user_id)
    client = LLMClient(provider=provider)

    used: list[str] = []
    messages = [
        {"role": "system", "content": ASK_SYSTEM},
        {"role": "user", "content": ASK_USER.format(
            report=json.dumps(_slim(report), ensure_ascii=False),
            facts=json.dumps({k: v for k, v in sorted(facts.items())},
                             ensure_ascii=False, default=str),
            question=question)},
    ]

    for _ in range(MAX_ASK_TOOLS):
        raw, _resp = client.chat_json(messages)

        # 模型要查东西
        if raw.get("calls"):
            from musicmind_agent.tools.base import call as run_tool
            for req in (raw.get("calls") or [])[:3]:
                name = req.get("tool")
                if name not in {t["name"] for t in catalog()}:
                    continue
                result = run_tool(name, ctx, req.get("args") or {})
                used.append(name)
            messages.append({"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)})
            messages.append({"role": "user", "content":
                             "工具结果已并入事实仓。现在给出回答。"})
            continue

        answer_text = raw.get("answer")
        if answer_text:
            from musicmind_agent.render import render_text
            return render_text(answer_text, ctx.facts, strict=False)

    return "这个问题我没能从数据里找到答案。"


def _slim(report: dict) -> dict:
    """报告压缩版。**别把整份塞进 prompt** —— 20 条推荐带理由就有几千 token，
    追问根本用不上，只会挤掉事实仓的位置。"""
    return {
        "headline": report.get("headline"),
        "dimensions": [
            {"dimension": d.get("dimension"), "summary": d.get("summary"),
             "claims": [c.get("text") for c in (d.get("claims") or [])]}
            for d in (report.get("dimensions") or [])
        ],
        "recommendations": [
            {"track_id": r.get("track_id"), "reason": r.get("reason")}
            for r in (report.get("recommendations") or [])[:5]
        ],
        "limitations": report.get("limitations"),
    }


def answer_and_persist(connection, run_id: int) -> None:
    from musicmind_agent.persist import claim_run, mark_failed

    run = claim_run(connection, run_id)
    if run is None:
        return

    row = None
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT report_json, facts_json FROM agent_report WHERE id=%s",
            (run["report_id"],))
        row = cursor.fetchone()
    if row is None:
        mark_failed(connection, run_id, "报告不存在")
        return

    report = row["report_json"]
    facts = row["facts_json"]
    if isinstance(report, str):
        report = json.loads(report)
    if isinstance(facts, str):
        facts = json.loads(facts)

    text = answer(connection, run["user_id"], report, facts,
                  run["question"], run["provider"])

    with connection.cursor() as cursor:
        # 先记用户那句，再记回答 —— 顺序就是 UI 里的显示顺序
        cursor.execute(
            "INSERT INTO agent_message (report_id, run_id, role, content) VALUES (%s,%s,'user',%s)",
            (run["report_id"], run_id, run["question"]))
        cursor.execute(
            "INSERT INTO agent_message (report_id, run_id, role, content) VALUES (%s,%s,'assistant',%s)",
            (run["report_id"], run_id, text))
        cursor.execute(
            "UPDATE agent_run SET status='DONE', finished_at=NOW() WHERE id=%s", (run_id,))
    connection.commit()
```

**先自己跑通再碰 Java**：

```bash
# 手工插一条 run，然后跑
.venv/Scripts/python.exe -c "
from musicmind_agent.db import get_connection
c=get_connection(); cur=c.cursor()
cur.execute(\"INSERT INTO agent_run (user_id, kind, provider) VALUES (34,'report','deepseek')\")
print('run_id =', cur.lastrowid); c.close()"

.venv/Scripts/python.exe -m musicmind_agent.cli run --run-id 1
# 看 agent_report 里有没有行
```

---

## 5~9. Java 侧

**照抄的三份模板**（这个仓库已经踩过所有坑，别自己重写）：

| 新建 | 照抄 |
|---|---|
| `AgentProperties` | `IngestionProperties`（字段换名字，加 `agent-service-dir` 和 `reco-count`） |
| `AgentRunMapper` | `IngestionJobMapper`（`claim` 的 WHERE 条件那条注释一定要看懂） |
| `AgentWorker` | `IngestionWorker`（子进程、超时强杀、崩溃恢复、60 秒清扫） |

**`AgentProperties`**：

```java
@Data
@Component
@ConfigurationProperties(prefix = "agent")
public class AgentProperties {
    /** agent-service 目录，也是子进程的工作目录 */
    private String agentServiceDir = "../agent-service";
    /** 【必须指到 .venv】系统 python 没装 langgraph / librosa */
    private String python = "../agent-service/.venv/Scripts/python.exe";
    private int jobTimeoutSeconds = 300;
    private long pollIntervalMs = 1500;
    private String logDir = "../logs/agent";
    private int recentRuns = 20;
}
```

`application.yaml` 加一节（路径相对 `backend/`，和现有的 `file:../.env` 同一套约定）：

```yaml
agent:
  agent-service-dir: ../agent-service
  python: ../agent-service/.venv/Scripts/python.exe
  job-timeout-seconds: 300          # 一次报告 30-50 秒，留足余量
  poll-interval-ms: 1500
  log-dir: ../logs/agent
  recent-runs: 20
```

**`AgentWorker` 的子进程模式**（直接抄 `IngestionWorker.runPipeline`，注意这四处）：

```java
ProcessBuilder builder = new ProcessBuilder(
        props.getPython(), "-m", "musicmind_agent.cli", "run",
        "--run-id", String.valueOf(runId));
builder.directory(new File(props.getAgentServiceDir()));
builder.redirectErrorStream(true);                       // 不合并 → 管道写满假死
builder.redirectOutput(ProcessBuilder.Redirect.appendTo(logFile.toFile()));
builder.environment().put("PYTHONIOENCODING", "utf-8");  // Windows GBK 会炸
// 超时 destroyForcibly；InterruptedException 时也要杀（否则孤儿进程继续写库）
```

**`AgentController`**：

```java
@RestController
@RequestMapping("/api/agent")
@RequiredArgsConstructor
public class AgentController {

    private final AgentService agentService;

    /** 排一次报告生成。**202 而不是 200** —— 一次要 30 秒，同步必然超时 */
    @PostMapping("/report")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> request(@RequestParam(defaultValue = "deepseek") String provider) {
        return agentService.requestReport(CurrentUser.id(), provider);
    }

    /** 排队追问 */
    @PostMapping("/ask")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> ask(@Valid @RequestBody AskRequest req) {
        return agentService.ask(CurrentUser.id(), req.getReportId(), req.getQuestion());
    }

    /** 轮询这个。返回 run 状态 + 报告（好了的话）+ 追问消息 */
    @GetMapping("/runs/{id}")
    public Map<String, Object> run(@PathVariable Long id) {
        return agentService.runStatus(CurrentUser.id(), id);
    }

    /** 我的报告列表 */
    @GetMapping("/reports")
    public List<Map<String, Object>> reports() {
        return agentService.listReports(CurrentUser.id());
    }
}
```

**`AgentService.runStatus` 的关键约束**：

```java
    // 【原样透传，不许解析】
    // report_json 是 agent-service 写的，schema 由那边定义。
    // Java 这边一旦出现 reportJson.get("dimensions") 这种代码，
    // 报告结构一改就要两边同时改 —— 而那种 bug 在生产上才现形。
    // 直接把它当字符串塞进返回的 Map 就行，前端自己 JSON.parse
```

`SecurityConfig` 不用改（login/register 之外默认全认证）。

---

## 11~13. 前端

**`api/persona.js`**：

```js
import http from './http'

/**
 * 排一次报告生成。
 *
 * 【为什么是 202 + 轮询】一次要 30 秒（实测 p50 28.7s / p95 33.2s），
 * 而 axios 默认 timeout 是 10 秒 —— 同步接口必然超时。
 */
export const apiRequestReport = (provider = 'deepseek') =>
  http.post('/agent/report', null, { params: { provider } })

export const apiAsk = (reportId, question) =>
  http.post('/agent/ask', { reportId, question })

/** { run: {id,status,errorMessage}, report: {...} | null, messages: [...] } */
export const apiRunStatus = (runId) => http.get(`/agent/runs/${runId}`)

export const apiMyReports = () => http.get('/agent/reports')
```

**`PersonaView.vue`** 的要点：

```vue
<!-- 三块内容，从下往上依赖 -->
<!-- 1. 没报告时：一个「生成」按钮 + 预计时长（要说清是 30 秒，别让用户干等） -->
<!-- 2. 有报告时：标题 / 各维度 / 推荐列表 / 局限 -->
<!-- 3. 报告下面：追问输入框 + 消息列表 -->

<!-- 轮询：和 MyPlaylistView 那套一模一样，空闲就停表 -->
<!-- 注意：生成中要显示「正在分析…」和已用时长，30 秒的白屏是留不住用户的 -->
```

**推荐列表要显示 `reason` 和 `relation_to_history.note`** —— 那是原则 4 的落点
（「为什么推荐」「和你过去喜欢的有什么关系」），是这个功能的卖点，别只列歌名。

**`router/index.js` + `App.vue`** 各一行，照 `ImportView` 的写法。

---

## 验收标准

1. **点「生成」→ 页面显示进度 → 30 秒内出报告**，全程不超时
2. **报告内容完整**：标题、≥4 个维度、20 条推荐（每条带理由）、局限
3. **追问能带证据回答**：问「我最常听哪个流派」，回答里的数字要能对上报告
4. **进程重启后历史还在**：刷新页面能重新读回上次的报告和追问
5. **越权**：B 读 A 的 reportId / runId → 404
6. **报告生成失败要能看到原因**（`error_message` 透到前端），不是白屏
7. **Java 端零解析**：`grep -rn "dimensions\|recommendations" backend/src/main/java/com/musicmind/` 应该只在注释里出现

---

## 五个坑

1. **子进程必须 `redirectErrorStream(true)`** —— 分两个流只读一个，另一个写满缓冲区时子进程假死。
2. **`PYTHONIOENCODING=utf-8`** —— Windows 上 python 输出重定向走 GBK，print 中文直接抛异常。
3. **超时强杀 + 中断也要杀** —— 否则孤儿 python 继续写库，下次启动又重跑同一个任务，两个进程写同一批表。
4. **报告 JSON 原样透传** —— 见上面那段注释，这是这三张表归属规则的落点。
5. **一次报告 30 秒** —— 前端必须给进度反馈。用户看不到进度的话，30 秒和卡死没区别。

---

## 写完发我什么

1. 一张页面截图（报告页）
2. 一次完整的追问往返（问题 + 回答）
3. 越权那两条的 HTTP 状态码
4. **你自己觉得哪块别扭** —— 尤其是「报告 JSON 原样透传」这条，前端要自己解析结构，
   你可能会有不同看法
