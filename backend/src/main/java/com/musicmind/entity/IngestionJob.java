package com.musicmind.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 一条按需入库任务（ingestion_job）。
 *
 * 【为什么要有这张表而不是直接在请求线程里干】
 * 一次入库 ≈ 6 秒（MusicBrainz 搜索 1s + 查 releases 1s + 子进程 2s + 写库），
 * 整单 814 首要一个多小时。HTTP 请求里同步做，用户看到的只有转圈和超时。
 * 存成行 → 后台单线程顺序消费 → 前端轮询进度。
 *
 * 【队列全局共享，不按用户隔离】——入库的产物（track / album 行）本来就写进
 * 所有人共用的音乐侧表。甲歌单里的歌不会因为乙点了「入库」而变得不能被甲收藏，
 * 这是特性：谁先点谁出力，成果大家用。user_id 只用于审计。
 */
@Data
public class IngestionJob {

    private Long id;

    /** 发起人。仅审计——队列不按用户隔离 */
    private Long userId;

    /** 触发的 user_playlist_track 行 id。故意没有外键：歌单删了，任务作为历史留着 */
    private Long trackRowId;

    /** 外部歌手名。重匹配时按它捞行 */
    private String artistName;

    private String title;

    /** 外部专辑名。挑 release 时的加分信号（同名专辑太多了） */
    private String albumName;

    private Long durationMs;

    private String releaseMbid;

    /** QUEUED / RUNNING / DONE / FAILED / NOT_FOUND */
    private String status;

    /** 入库完成后回头对上号的行数。0 不一定有问题——那张专辑可能一首都没对上 */
    private Integer rematchedCount;

    private String errorMessage;

    private LocalDateTime startedAt;

    private LocalDateTime finishedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
