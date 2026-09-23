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
}