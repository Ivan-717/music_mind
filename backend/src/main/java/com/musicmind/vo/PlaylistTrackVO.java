package com.musicmind.vo;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class PlaylistTrackVO {
    private Long trackId;
    private String name;
    private Long durationMs;
    private Integer sortOrder;
    private Long albumId;
    private String albumName;
    private String artistNames;
    private LocalDateTime addedAt;
    /** 有没有 30 秒试听。没试听源的曲目不给 ▶（和专辑/歌单/搜索同一规矩） */
    private Boolean hasPreview;
}
