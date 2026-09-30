package com.musicmind.entity;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class Playlist {
    private Long id;
    private Long userId;
    private String name;
    private String description;
    private Boolean isPublic;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
