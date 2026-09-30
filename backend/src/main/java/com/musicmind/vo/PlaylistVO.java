package com.musicmind.vo;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class PlaylistVO {
    private Long id;
    private String name;
    private String description;
    private Boolean isPublic;
    private Integer trackCount;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
