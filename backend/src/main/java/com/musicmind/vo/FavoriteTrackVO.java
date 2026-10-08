package com.musicmind.vo;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class FavoriteTrackVO {
    private Long trackId;       // ← track_id
    private String name;        // ← name
    private Long durationMs;    // ← duration_ms
    private Long albumId;       // ← album_id
    private String albumName;   // ← album_name
    private String artistNames; // ← artist_names
    private LocalDateTime favoritedAt;  // ← favorited_at
    /** 有没有 30 秒试听。前端据此决定给不给 ▶（没试听的不给按钮） */
    private Boolean hasPreview;
}