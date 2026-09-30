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
    private Long durationMs;
    private String coverUrl;
    /** PENDING / MATCHED / UNRESOLVED */
    private String matchStatus;
    private Long matchedTrackId;
    private LocalDateTime matchedAt;
}
