package com.musicmind.entity;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class UserPlaylistImport {
    private Long id;
    private Long userId;
    private String provider;
    private String externalPlaylistId;
    private String playlistName;
    private String sourceUrl;
    private Integer trackCount;
    private LocalDateTime lastImportedAt;
}
