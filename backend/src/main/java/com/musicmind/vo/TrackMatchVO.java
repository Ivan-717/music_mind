package com.musicmind.vo;

import lombok.Data;

/** 歌单导入时，本地匹配到的一首曲目 */
@Data
public class TrackMatchVO {
    private Long trackId;
    private String trackName;
    private Long albumId;
    private String albumName;
}
