package com.musicmind.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 按需入库的运行参数，见 application.yaml 的 ingestion 节。
 *
 * 默认值都是相对 backend/ 的路径（和 application.yaml 里 `file:../.env` 同一套约定：
 * 服务的工作目录就是 backend/）。换机器时改 yaml，不用改代码。
 */
@Data
@Component
@ConfigurationProperties(prefix = "ingestion")
public class IngestionProperties {

    /** data-pipeline 目录，也是子进程的工作目录 */
    private String dataPipelineDir = "../data-pipeline";

    /**
     * 跑管道的 Python。
     *
     * 【必须指到 .venv 里的那个】系统 python 没装 requests / python-dotenv，
     * 用它起子进程会以 ModuleNotFoundError 失败，而且从 Java 这边看只是一个非 0 退出码。
     */
    private String python = "../data-pipeline/.venv/Scripts/python.exe";

    private String script = "ingest_release.py";

    /** 一条任务最多跑多久。超时强杀并按 FAILED 收尾，否则 worker 会被一个卡死的子进程拖住整条队列 */
    private int jobTimeoutSeconds = 300;

    /** 队列空转时的轮询间隔 */
    private long pollIntervalMs = 1500;

    /** 子进程输出落盘的目录。按 job id 分文件，失败时从文件尾部取原因 */
    private String logDir = "../logs/ingestion";

    /** 状态接口回传多少条历史任务 */
    private int recentJobs = 20;

    /**
     * worker 是否随应用启动就开始消费队列。
     *
     * 【测试里必须设成 false】@SpringBootTest 会起整个上下文，
     * 本地队列里躺着几百条任务时跑 mvn test，测试会真的去抓取、真的写库。
     * 用户跑测试不该改数据。
     */
    private boolean workerEnabled = true;
}
