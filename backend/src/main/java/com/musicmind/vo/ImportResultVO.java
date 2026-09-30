package com.musicmind.vo;

import lombok.Data;

import java.util.List;

@Data
public class ImportResultVO {
    private String provider;        // netease / qq
    private String playlistName;
    private String sourceUrl;

    private int parsed;             // 从歌单里取到多少首
    private int matched;            // 本地库里匹配上多少首
    private int added;              // 实际新加入收藏多少首（已收藏的不算）
    private int alreadyFavorited;   // 本来就已收藏的

    private List<ImportItemVO> items = List.of();
}
