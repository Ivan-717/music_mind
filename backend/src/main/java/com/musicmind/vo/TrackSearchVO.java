package com.musicmind.vo;

import lombok.Data;

@Data
public class TrackSearchVO {
    private Long trackId;
    private String name;
    private Long durationMs;
    private Long albumId;
    private String albumName;
    private String artistNames;
}
