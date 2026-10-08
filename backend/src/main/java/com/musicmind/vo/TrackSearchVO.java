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
    /** 有没有 30 秒试听。前端据此决定给不给 ▶（没试听的不给按钮） */
    private Boolean hasPreview;
}
