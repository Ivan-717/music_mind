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
}
