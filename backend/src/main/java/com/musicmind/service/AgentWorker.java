package com.musicmind.service;

import com.musicmind.config.AgentProperties;
import com.musicmind.entity.AgentRun;
import com.musicmind.mapper.AgentRunMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.SmartLifecycle;
import org.springframework.stereotype.Component;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Agent 队列的执行者：单线程顺序消费 agent_run。
 *
 * 形状照 IngestionWorker。四处地方是这个仓库已经踩过的坑，不要改：
 *   1. redirectErrorStream(true) —— 分两个流只读一个，另一个写满缓冲区时子进程假死
 *   2. PYTHONIOENCODING=utf-8 —— Windows 下 python 输出重定向走 GBK，print 中文抛异常
 *   3. InterruptedException 时也要 destroyForcibly —— 否则孤儿进程继续写库
 *   4. 运行期清扫卡死的 RUNNING —— 只在启动时扫一次兜不住「python 写状态那步自己失败」
 *
 * 【为什么单线程】一次报告 30 秒，主要成本是等 LLM 和跑图。
 * 并发跑不会更快（provider 有限流），只会让失败原因难以复现。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AgentWorker implements SmartLifecycle {

    /** 清扫卡死任务的间隔 */
    private static final long SWEEP_INTERVAL_MS = 60_000;

    private final AgentRunMapper runMapper;
    private final AgentProperties props;

    private final AtomicBoolean alive = new AtomicBoolean(false);
    private final AtomicBoolean paused = new AtomicBoolean(false);

    private volatile Thread thread;
    private volatile Long currentRunId;
    private volatile String currentLabel;
    private long lastSweepAt = 0;

    // ============================================================
    // 生命周期
    // ============================================================

    /**
     * 测试里不自动启动（agent.worker-enabled=false）。
     *
     * 【为什么不是把 bean 整个去掉】AgentService 依赖它，
     * @ConditionalOnProperty 一关上下文就起不来。保留 bean、
     * 只是不启动线程，依赖关系和接口行为都不变。
     */
    @Override
    public boolean isAutoStartup() {
        return props.isWorkerEnabled();
    }

    @Override
    public void start() {
        if (!alive.compareAndSet(false, true)) {
            return;
        }
        thread = new Thread(this::loop, "agent-worker");
        thread.setDaemon(true);
        thread.start();
        log.info("Agent worker 已启动");
    }

    @Override
    public void stop() {
        alive.set(false);
        Thread t = thread;
        if (t != null) {
            t.interrupt();
        }
    }

    @Override
    public boolean isRunning() {
        return alive.get();
    }

    public boolean isPaused() {
        return paused.get();
    }

    public void pause() {
        paused.set(true);
    }

    public void resume() {
        paused.set(false);
    }

    public Long getCurrentRunId() {
        return currentRunId;
    }

    public String getCurrentLabel() {
        return currentLabel;
    }

    // ============================================================
    // 主循环
    // ============================================================

    private void loop() {
        try {
            runLoop();
        } catch (Throwable t) {
            // 【连 Error 也兜住】线程死了但 isRunning() 还返回 true 是最糟的组合：
            // Spring 认为它活着不会重启，队列从此不再被消费，界面上却看不出异常
            log.error("Agent worker 异常退出，队列已停止消费（需重启后端）", t);
        } finally {
            alive.set(false);
        }
    }

    private void runLoop() {
        int requeued = runMapper.requeueRunning();
        if (requeued > 0) {
            log.info("把 {} 条上次没跑完的任务打回队列", requeued);
        }

        while (alive.get()) {
            sweepStale();

            try {
                if (paused.get()) {
                    idle();
                    continue;
                }

                AgentRun run = runMapper.selectNextQueued();
                if (run == null) {
                    idle();
                    continue;
                }
                if (runMapper.claim(run.getId()) == 0) {
                    continue;   // 被别的实例抢走了
                }

                process(run);

            } catch (Exception e) {
                log.warn("Agent worker 单轮异常，稍后重试", e);
                idle();
            }
        }
    }

    private void idle() {
        try {
            Thread.sleep(props.getPollIntervalMs());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            alive.set(false);
        }
    }

    private void sweepStale() {
        long now = System.currentTimeMillis();
        if (now - lastSweepAt < SWEEP_INTERVAL_MS) {
            return;
        }
        lastSweepAt = now;
        try {
            int n = runMapper.requeueStale(props.getJobTimeoutSeconds() * 2L);
            if (n > 0) {
                log.warn("把 {} 条卡死的 RUNNING 任务打回队列", n);
            }
        } catch (Exception e) {
            log.warn("清扫卡死任务失败：{}", e.toString());
        }
    }

    // ============================================================
    // 单条任务
    // ============================================================

    private void process(AgentRun run) {
        currentRunId = run.getId();
        // 【标签里不能带问题原文】/api/agent/status 返回 currentLabel，而那个
        // 端点对任何登录用户开放 —— 带上问题就等于把别人的追问片段广播出去。
        // 它只需要说清「队列在忙什么」，不需要说忙的是谁问了什么
        currentLabel = "report".equals(run.getKind()) ? "生成报告" : "回答追问";
        long startedAt = System.currentTimeMillis();

        // 【python 自己写状态】Java 这边不写 DONE / FAILED ——
        // 真实结果（成功还是失败、报告 id 是多少）只有子进程知道。
        // 这里只负责起进程、等它、超时强杀。
        // 【kind → 子命令必须一一对上】原来写的是「不是 report 就当 ask」——
        // 加了 kind='chat' 之后，对话任务会被当成追问跑，Python 那边去找报告，
        // 报「报告不存在」，而那个措辞会让人以为报告真的没了。
        // 加新 kind 时这里必须跟着改，否则失败信息指向完全无关的地方
        String subcommand = switch (run.getKind()) {
            case "report" -> "run";
            case "chat" -> "chat";
            default -> "ask";
        };
        String failure = runPython(subcommand, run.getId());

        if (failure != null) {
            // 子进程都没跑成（启动失败/超时），这时 python 没机会写状态，
            // 只能 Java 兜底把它标成 FAILED，否则永远停在 RUNNING
            runMapper.finishFailed(run.getId(), truncate(failure, 900));
            log.warn("任务 {} 失败：{}", run.getId(), failure);
        } else {
            log.info("任务 {} 的子进程已退出，耗时 {}ms",
                    run.getId(), System.currentTimeMillis() - startedAt);
        }

        currentRunId = null;
        currentLabel = null;
    }

    // ============================================================
    // 子进程
    // ============================================================

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
            builder.redirectOutput(ProcessBuilder.Redirect.appendTo(logFile.toFile()));
            builder.environment().put("PYTHONIOENCODING", "utf-8");

            Process process = builder.start();

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

            if (process.exitValue() != 0) {
                return tail(logFile, 500);
            }
            return null;

        } catch (IOException e) {
            return "起子进程失败：" + e.getMessage();
        }
    }

    /** 日志尾部。报错信息在最后几行，取尾部比取开头有用 */
    private static String tail(Path file, int maxChars) {
        try {
            String content = Files.readString(file, StandardCharsets.UTF_8).trim();
            if (content.isEmpty()) {
                return "子进程非 0 退出，但没有输出";
            }
            return content.length() <= maxChars
                    ? content
                    : content.substring(content.length() - maxChars);
        } catch (Exception e) {
            return "子进程非 0 退出，日志读取失败：" + e;
        }
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.length() <= max ? s : s.substring(0, max);
    }
}
