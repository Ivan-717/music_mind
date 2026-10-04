package com.musicmind.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Agent 运行参数，见 application.yaml 的 agent 节。
 *
 * 形状照 IngestionProperties（那套已经跑了几百条任务，坑都踩过了）。
 * 默认值都相对 backend/ —— 和 application.yaml 里 `file:../.env` 同一套约定：
 * 服务的工作目录就是 backend/。
 */
@Data
@Component
@ConfigurationProperties(prefix = "agent")
public class AgentProperties {

    /** agent-service 目录，也是子进程的工作目录 */
    private String agentServiceDir = "../agent-service";

    /**
     * 跑 Agent 的 Python。
     *
     * 【必须指到 .venv 里的那个】系统 python 没装 langgraph / librosa，
     * 用它起子进程会以 ModuleNotFoundError 失败，从 Java 这边只能看到一个非 0 退出码。
     */
    private String python = "../agent-service/.venv/Scripts/python.exe";

    /**
     * 一条任务最多跑多久。
     *
     * 【比 ingestion 那边宽得多】一次报告要 30 秒（实测 p50 28.7s / p95 33.2s），
     * 而千问那种慢的 provider 单步 compose 就要 60 秒。300 秒是留足余量，
     * 不是保守 —— 卡太紧会把正常的长任务误杀成 FAILED。
     */
    private int jobTimeoutSeconds = 300;

    /** 队列空转时的轮询间隔 */
    private long pollIntervalMs = 1500;

    /** 子进程输出落盘的目录。按 run id 分文件，失败时从文件尾部取原因 */
    private String logDir = "../logs/agent";

    /** 状态接口回传多少条历史任务 */
    private int recentRuns = 20;

    /**
     * worker 是否随应用启动就开始消费队列。
     *
     * 【测试里必须设成 false】@SpringBootTest 会起整个上下文，
     * 跑 mvn test 时不该真的去起子进程、烧 LLM 的额度。
     */
    private boolean workerEnabled = true;
}
