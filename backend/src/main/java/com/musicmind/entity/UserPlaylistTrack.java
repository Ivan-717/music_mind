package com.musicmind.entity;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class UserPlaylistTrack {
    private Long id;
    private Long importId;
    private Long userId;
    private String provider;
    private String externalId;
    private Integer position;
    private String title;
    private String artists;
    private String albumName;
    /** 发行年（导入时补抓）。未入库的歌靠它进「年代」维度 */
    private Integer releaseYear;
    private Long durationMs;
    private String coverUrl;
    /** PENDING / MATCHED / UNRESOLVED */
    private String matchStatus;
    private Long matchedTrackId;
    private LocalDateTime matchedAt;
}
