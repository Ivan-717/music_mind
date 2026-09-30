package com.musicmind.vo;

import lombok.Data;

@Data
public class ImportedTrackVO {
    /** user_playlist_track 那一行的 id，剔除歌曲时用它 */
    private Long id;
    private String externalId;
    private Integer position;
    private String title;
    private String artists;
    private String albumName;
    private Long durationMs;
    private String coverUrl;
    /** PENDING / MATCHED / UNRESOLVED */
    private String matchStatus;
    /** 对齐到的本地曲目 id；没对齐是 null，前端拿它调收藏接口 */
    private Long matchedTrackId;
    /** 当前用户收藏了没有。没对齐的歌恒为 false */
    private Boolean favorited;
}
