package com.musicmind.vo;

import lombok.Data;

/**
 * 入库之后要回头重试对齐的一行（user_playlist_track）。
 *
 * 只带重匹配必需的字段：定位（importId + externalId）、
 * 以及喂给 matchTrack 的三个参数（title / artists / durationMs）。
 */
@Data
public class RematchCandidateVO {

    /** user_playlist_track 的主键。updateMatch 用 importId + externalId 定位，这个只用于日志 */
    private Long rowId;

    private Long importId;

    private String externalId;

    private String title;

    /** 外部原样，形如「周杰伦 / 温岚」，可能为 null */
    private String artists;

    private Long durationMs;
}
