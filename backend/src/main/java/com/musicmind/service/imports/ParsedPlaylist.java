package com.musicmind.service.imports;

import lombok.Data;

import java.util.List;

@Data
public class ParsedPlaylist {
    /** 平台标识：netease / qq */
    private String provider;
    /** 平台上这个歌单的 id。落库去重靠它——同一个人重复导入同一个歌单要更新而不是新建 */
    private String externalId;
    private String name;

    /** 歌单标签（网易云的 playlist.tags，逗号分隔）。用户口味的粗粒度信号 */
    private String tags;

    private List<ParsedTrack> tracks = List.of();
}
