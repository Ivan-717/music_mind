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
    /** 有没有 30 秒试听（track_audio_feature.preview_url）。前端据此决定给不给 ▶ */
    private Boolean hasPreview;
}
