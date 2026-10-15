# SSE 流式进度交接：把 20-40 秒的黑盒变成「看得见的进度」

**这一步是你的**（Python 和 Java 两层；前端消费和验收脚本我来写）。
目标：深夜电台发问后，页面上不再是「正在查数据… 17 秒」的傻等，
而是**实时进度**：「正在理解你的问题…」→「已查：search_tracks（12 条）」→
「正在写回答…」→ 结果落定。

---

## 一个必须先说清的设计判断：**阶段 1 做「纯进度旁路」，不做 token 级流式**

chat 的最终产物是**一个 JSON**（answer + recommendations + fetch_proposals + path），
token 级流式会把 `{"answer": "挑了几首…` 这种碎片推给用户——不能看。
要做到「回答逐字出现」得把最终输出拆成两段调用（先纯文本流式、再 JSON 补丁），
那是**阶段 2**的事，等阶段 1 验收后另开规格。

阶段 1 的形态：**在现有管道旁边加一条进度旁路**——

```
正确性完全不变：消息落定仍然靠 GET /runs/{id} 轮询（保留为兜底）
进度感是新增：SSE 推 stage 事件 → 前端只用来更新一行进度文案
```

这样每一层都可以单独回归（轮询坏了是老 bug，进度断了只是少了文案）。

## 协议：NDJSON over 子进程 stdout → SSE

```
Python stdout（每行一个 JSON，必须 flush）:
  {"t": "stage", "note": "正在理解你的问题…"}
  {"t": "stage", "note": "已查：search_tracks（12 条）"}
  CHAT_OK 42            ← 结尾标记保持原样（Java 读线程不解析它也没事）

Java 读线程逐行读 → 日志照旧写文件 → 行以 {"t" 开头就解析 → 推给 SSE:
  event: stage
  data: {"note": "已查：search_tracks（12 条）"}
```

---

## 改动清单（按层，标了谁写）

| 层 | 文件 | 动作 | 谁 |
|---|---|---|---|
| Python | `musicmind_agent/chat.py` | `chat()` / `chat_and_persist()` 加 `on_stage` 回调 + 三处打点 | 你 |
| Python | `musicmind_agent/cli.py` | `cmd_chat` 把 on_stage 实现为 stdout NDJSON | 你 |
| Java | `service/AgentEventRegistry.java` | **新建**：SseEmitter 注册表（和 AgentWorker 同包） | 你 |
| Java | `service/AgentWorker.java` | `runPython` 的输出从「直写日志文件」改 **PIPE + 读线程** | 你 |
| Java | `controller/AgentController.java` | 新端点 `GET /api/agent/runs/{id}/stream` | 你 |
| 前端 | `api/chat.js`、`views/ExploreView.vue` | fetch-stream 消费（我写） | 我 |
| 验收 | `scripts/check_sse.py` | 端到端 SSE 断言（我写） | 我 |

---

## 完整代码

### 1. `chat.py` —— 打点（回调是旁路，坏一点也不许影响主流程）

`chat()` 签名加 `on_stage`，函数体开头：

```python
def chat(connection, user_id: int, message: str,
         history: list[dict], provider: str,
         on_stage=None) -> dict:
    ...

    def stage(note: str) -> None:
        """进度是旁路 —— 回调抛异常绝不能影响回答本身。"""
        if on_stage is None:
            return
        try:
            on_stage(note)
        except Exception:
            pass
```

循环里三处打点（位置对应现有代码，`for _round in range(MAX_CHAT_ROUNDS):`）：

```python
    for _round in range(MAX_CHAT_ROUNDS):
        # 第 1 轮 = 模型在读你的问题；之后的轮次 = 上一轮工具结果已喂回，
        # 模型正在写（如果它又要调工具，下面的「已查」会立刻覆盖，信息不会卡住）
        stage("正在理解你的问题…" if _round == 0 else "正在写回答…")

        raw, _resp = client.chat_json(messages)
        calls = raw.get("calls") or []
        if calls:
            for req in calls[:MAX_TOOLS_PER_ROUND]:
                ...
                result = call(name, ctx, req.get("args") or {})
                ...
                rows = len(result.rows or [])
                stage(f"已查：{name}（{rows} 条）" if rows else f"已查：{name}")
```

`chat_and_persist()` 同步透传：

```python
def chat_and_persist(connection, run_id: int, on_stage=None) -> None:
    ...
    out = chat(connection, user_id, run["question"], history, provider,
               on_stage=on_stage)
```

### 2. `cli.py` —— NDJSON 输出（**必须 flush**）

```python
def cmd_chat(args: argparse.Namespace) -> int:
    """跑一轮对话并落库。Java 子进程调的就是这个。"""
    from musicmind_agent.chat import chat_and_persist
    from musicmind_agent.persist import mark_failed

    def emit(note: str) -> None:
        # 【flush 是命门】stdout 默认块缓冲 —— 不 flush 的话进度全攒在
        # 缓冲区里，Java 读线程要等进程退出才看得到，等于没流
        print(json.dumps({"t": "stage", "note": note}, ensure_ascii=False),
              flush=True)

    connection = get_connection()
    try:
        chat_and_persist(connection, args.run_id, on_stage=emit)
    except Exception as e:
        ...  # 原样不动（CHAT_FAIL 走 stderr，读线程按「不是 JSON 的行」处理）
    finally:
        connection.close()

    print(f"CHAT_OK {args.run_id}")   # 结尾标记保持原样
    return 0
```

### 3. `service/AgentEventRegistry.java`（新建）

```java
package com.musicmind.service;

import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 正在被订阅的 run 进度通道。
 *
 * 【没人订阅是常态】大多数 run（报告/追问）没有前端开 SSE —— 查不到
 * emitter 就安静丢掉，这不是错误。写事件失败（客户端断了）也只摘牌。
 */
@Component
public class AgentEventRegistry {

    private final Map<Long, SseEmitter> emitters = new ConcurrentHashMap<>();

    /** 前端订阅时注册。超时要显式设 —— 默认值很短，一轮 chat 要 20-40 秒 */
    public SseEmitter register(Long runId) {
        SseEmitter emitter = new SseEmitter(5 * 60 * 1000L);
        emitters.put(runId, emitter);
        Runnable remove = () -> emitters.remove(runId, emitter);
        emitter.onCompletion(remove);
        emitter.onTimeout(remove);
        emitter.onError(e -> remove.run());
        // 【首帧必须立刻发】SseEmitter 在第一次 send 前不会下发响应头 ——
        // 客户端会一直挂着（实测 curl 5 秒零字节，验收脚本直接判连不上）。
        // hello 帧既解除阻塞，也让订阅方知道「连上了，进度马上来」
        try {
            emitter.send(SseEmitter.event().name("stage")
                    .data(Map.of("note", "已连上，等进度…")));
        } catch (Exception e) {
            emitters.remove(runId, emitter);
        }
        return emitter;
    }

    /** run 结束（AgentWorker 的 process() 末尾调）：把还在看的客户端正常
     *  关流，否则连接要挂到 5 分钟超时。没人订阅就什么都不做。 */
    public void complete(Long runId) {
        SseEmitter emitter = emitters.remove(runId);
        if (emitter == null) return;
        try {
            emitter.complete();
        } catch (Exception ignored) {
        }
    }

    public void stage(Long runId, String note) {
        SseEmitter emitter = emitters.get(runId);
        if (emitter == null) return;
        try {
            emitter.send(SseEmitter.event().name("stage")
                    .data(Map.of("note", note)));
        } catch (Exception e) {
            emitters.remove(runId, emitter);   // 客户端断了，摘牌即可
        }
    }
}
```

### 4. `AgentWorker.java` —— runPython 改 PIPE + 读线程

**文件**：`backend/src/main/java/com/musicmind/service/AgentWorker.java`
（package `com.musicmind.service`，类头不动：`@Slf4j @Component @RequiredArgsConstructor`）

**① import 区**增补四行（其余已有的 `File/IOException/StandardCharsets/Files/Path/Paths/TimeUnit` 复用）：

```java
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.InputStreamReader;
import java.nio.file.StandardOpenOption;
```

**② 字段区**加一个字段（`@RequiredArgsConstructor` 自动进构造器，别的手工不动）：

```java
    private final AgentEventRegistry eventRegistry;
```

**③ `runPython` 整个方法替换为**（只改了两处：writer 换 PIPE + 起读线程；
其余分支——超时/中断/退出码——原样保留）：

```java
    /** 起 python 子进程。成功（退出码 0）返回 null，失败返回原因 */
    private String runPython(String subcommand, Long runId) {
        Path logFile = Paths.get(props.getLogDir()).resolve("run-" + runId + ".log");
        try {
            Path parent = logFile.getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }

            ProcessBuilder builder = new ProcessBuilder(
                    props.getPython(), "-m", "musicmind_agent.cli",
                    subcommand, "--run-id", String.valueOf(runId));
            builder.directory(new File(props.getAgentServiceDir()));

            // 见类注释的 1、2 —— 这两条不设，失败现场会非常误导
            builder.redirectErrorStream(true);
            // 【本次改动】原来 stdout 直写日志文件（appendTo），Java 看不到内容；
            // 现在 PIPE 自己读：一行两用 —— 照旧落日志 + 是 NDJSON 就转发。
            // redirectErrorStream(true) 保持不动：stderr 混进来只是「不是 JSON 的行」，
            // 读线程按普通日志放过，不破坏解析
            builder.redirectOutput(ProcessBuilder.Redirect.PIPE);
            builder.environment().put("PYTHONIOENCODING", "utf-8");

            Process process = builder.start();

            Thread reader = new Thread(() -> pumpOutput(process, runId, logFile),
                    "agent-stdout-" + runId);
            reader.setDaemon(true);
            reader.start();

            try {
                if (!process.waitFor(props.getJobTimeoutSeconds(), TimeUnit.SECONDS)) {
                    process.destroyForcibly();
                    return "超时（超过 " + props.getJobTimeoutSeconds() + " 秒）";
                }
            } catch (InterruptedException e) {
                // 见类注释的 3 —— Windows 下父进程退出不会终止子进程，
                // 它会变成孤儿继续烧 LLM 的额度
                process.destroyForcibly();
                Thread.currentThread().interrupt();
                return "被中断";
            }
            try {
                reader.join(500);   // 正常退出：等读线程把管道尾巴排干，日志不丢行
            } catch (InterruptedException e) {
                // join 也抛检查异常 —— 这里不写的话编译不过（初稿就漏了）
                Thread.currentThread().interrupt();
            }

            // 【④ 另有一处】process() 方法末尾（currentRunId = null; 之前）加一行：
            //     eventRegistry.complete(run.getId());
            //   run 结束后把订阅正常关流 —— 不关的话客户端要挂到 5 分钟超时

            if (process.exitValue() != 0) {
                return tail(logFile, 500);
            }
            return null;

        } catch (IOException e) {
            return "起子进程失败：" + e.getMessage();
        }
    }

    /** stdout 一行两用：照旧落日志；是 NDJSON stage 事件就转发给等进度的人。

     * 进程被强杀时管道断掉是预期路径（IOException 静默）；半行/坏 JSON
     * 按普通日志放过 —— 进度坏一点，绝不许影响任务本身。 */
    private void pumpOutput(Process process, Long runId, Path logFile) {
        ObjectMapper mapper = new ObjectMapper();
        try (BufferedReader in = new BufferedReader(
                     new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8));
             BufferedWriter logOut = Files.newBufferedWriter(logFile, StandardCharsets.UTF_8,
                     StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
            String line;
            while ((line = in.readLine()) != null) {
                logOut.write(line);
                logOut.newLine();
                logOut.flush();
                if (!line.startsWith("{\"t\"")) continue;
                try {
                    JsonNode node = mapper.readTree(line);
                    if ("stage".equals(node.path("t").asText())) {
                        eventRegistry.stage(runId, node.path("note").asText());
                    }
                } catch (Exception ignored) {
                }
            }
        } catch (IOException ignored) {
        }
    }
```

### 5. `AgentController.java` + `AgentService.java` —— SSE 端点与归属校验

**文件**：`backend/src/main/java/com/musicmind/controller/AgentController.java`
（package `com.musicmind.controller`；类头不动：`@RestController @RequestMapping("/api/agent") @RequiredArgsConstructor`）

**① import 区**增补三行：

```java
import com.musicmind.service.AgentEventRegistry;
import org.springframework.http.MediaType;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
```

**② 字段区**加一个字段（同 Worker，`@RequiredArgsConstructor` 自动进构造器）：

```java
    private final AgentEventRegistry eventRegistry;
```

**③ 类里加这个端点**（放在现有 `GET /runs/{id}` 后面，两块是一对）：

```java
    /**
     * 订阅一轮 run 的实时进度（阶段 1：只有 stage 事件，数据仍走轮询）。
     *
     * 【为什么前端不用 EventSource】它带不了 Authorization 头；前端走
     * fetch + ReadableStream 手写 SSE 解析（见 api/chat.js 的 streamRun）。
     * 【归属校验】不属于当前用户直接 404 —— 和 /runs/{id} 同一句话术。
     */
    @GetMapping(path = "/runs/{id}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(@PathVariable Long id) {
        agentService.assertRunOwned(id, CurrentUser.id());
        return eventRegistry.register(id);
    }
```

**④ `AgentService.java`**（`backend/src/main/java/com/musicmind/service/AgentService.java`）
加这个方法——**不用动 runStatus**（它内部本来就是 `runMapper.findOwned`，
这个方法只是把同一句校验单独露出来给 stream 端点用）：

```java
    /** 校验这条 run 属于当前用户 —— 不是就 404（和 runStatus 同一句话术） */
    public void assertRunOwned(Long runId, Long userId) {
        if (runMapper.findOwned(runId, userId) == null) {
            throw new ApiException(404, "任务不存在");
        }
    }
```

### 6. 前端（我写，列出形状方便你对齐）

`api/chat.js` 加 `streamRun(runId, onNote)`（fetch + ReadableStream，Bearer 头），
`ExploreView.vue`：send 成功后开流，进度文案行从「正在查数据… N 秒」变为
「{stageNote || '正在查数据…'} · N 秒」；stopPoll/onUnmounted 时 abort。

---

## 验收（我来跑，你先把三层写完）

顺序（每一步都能单独停）：

```bash
# 1. Python 单层：绕过 Java 和落库，直接调 chat() 看事件流（可直接复制）
cd agent-service
.venv/Scripts/python.exe -c "
import json
from musicmind_agent.db import get_connection
from musicmind_agent.chat import chat

conn = get_connection()
def emit(note):
    print(json.dumps({'t': 'stage', 'note': note}, ensure_ascii=False), flush=True)

out = chat(conn, 34, '推荐几首安静的', [], 'deepseek', on_stage=emit)
print('DONE:', out['answer'][:60])
conn.close()"
#   预期：事件「一个个冒出来」（正在理解 → 已查：search_tracks（N 条）→ 正在写回答）
#   20-40 秒后 DONE。**如果全在最后一起出现 = flush 没生效**，回查 cli/print。

# 2. Java 层：起后端，POST /api/agent/chat 拿 runId，然后
curl -N -H "Authorization: Bearer <token>" \
  http://localhost:8080/api/agent/runs/<runId>/stream
#   预期：event: stage / data: {"note":"..."} 逐条到达，先「正在理解」后「已查」

# 3. 前端：深夜电台发一句，进度文案应该实时变化（不是固定「正在查数据」）

# 4. 兜底回归：SSE 端点停掉（或断网模拟）→ 发问仍能正常拿到回答（轮询兜底未坏）
```

我会把 2、3、4 写成 `scripts/check_sse.py`（含真实发一轮 chat，约花 30 秒
LLM 时间），写完贴到这里。

---

## 完成后（简历话术素材）

「对话链路从 3 秒轮询改为 SSE 推送：Python 子进程 NDJSON → Java SseEmitter →
前端 fetch-stream；数据正确性不依赖流（轮询兜底），流只做进度旁路」——
架构上「旁路可降级」的取舍本身就是面试可讲的点。
