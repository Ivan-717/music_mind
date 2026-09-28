package com.musicmind.vo;

import lombok.Data;

@Data
public class AlbumTrackVO {
    private Long trackId;
    private String name;
    private Long durationMs;
    private Integer discNumber;
    private Integer trackNumber;
    private String artistNames;
}
