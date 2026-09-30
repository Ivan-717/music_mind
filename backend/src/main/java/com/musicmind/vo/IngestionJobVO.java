package com.musicmind.vo;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 一条入库任务的展示视图。
 *
 * 【不是直接返回实体】——实体带着 user_id，而队列是全局共享的，
 * 直接把实体扔出去等于把别人的用户 id 暴露给当前用户。
 */
@Data
public class IngestionJobVO {

    private Long id;

    /** 对应 user_playlist_track 的行 id。前端用它把那一行标成「抓取中」 */
    private Long trackRowId;

    private String artistName;

    private String title;

    private String albumName;

    /** 解析出的 release MBID。null = 还没解析出来或没找到 */
    private String releaseMbid;

    /** QUEUED / RUNNING / DONE / FAILED / NOT_FOUND */
    private String status;

    private Integer rematchedCount;

    private String errorMessage;

    private LocalDateTime startedAt;

    private LocalDateTime finishedAt;
}
