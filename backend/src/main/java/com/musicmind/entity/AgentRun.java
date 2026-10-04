package com.musicmind.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 一条 Agent 任务（agent_run）。
 *
 * 【为什么要有队列表】一次报告实测 30 秒（p50 28.7s / p95 33.2s），
 * 而前端 axios 默认 timeout 是 10 秒 —— 在 HTTP 线程里同步跑必然超时。
 * 存成行 → 后台单线程顺序消费 → 前端轮询。
 *
 * 【这张表归谁写】归属规则见 schema-user.sql 头注释的第三条：
 * agent_run / agent_report / agent_message 归 agent-service 写，Spring Boot 只读。
 * 唯一的例外是这里 —— Java 建行（这也是「排队」这个动作本身），
 * 但状态流转和报告内容都由 python 那边写。
 */
@Data
public class AgentRun {

    private Long id;

    private Long userId;

    /** report / ask */
    private String kind;

    /** ask 模式的问题 */
    private String question;

    /** ask 针对哪份报告；report 完成后由 python 回填 */
    private Long reportId;

    private String provider;

    /**
     * 这一趟分析哪些曲目：all / favorites / playlist。
     *
     * 【为什么范围写在 run 上而不是靠参数传】Python 子进程只拿到一个 run-id，
     * 它得自己去库里读这一趟该分析什么。参数多一条传递路径就多一处可能不一致。
     */
    private String scopeKind;

    /** scopeKind=playlist 时是 user_playlist_import.id，其余为 null */
    private Long scopeRef;

    /** QUEUED / RUNNING / DONE / FAILED */
    private String status;

    private String errorMessage;

    private LocalDateTime startedAt;

    private LocalDateTime finishedAt;

    private LocalDateTime createdAt;
}
