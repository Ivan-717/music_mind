package com.musicmind.vo;

import lombok.Data;

import java.util.List;

@Data
public class SearchVO {
    private String keyword;
    /** 关键词的繁简变体。返回给前端是有意的——让扩展逻辑在界面上可见 */
    private List<String> variants = List.of();

    /**
     * 每一类的【总匹配数】，不受 limit 影响。
     * 前端用它显示「歌曲 20 / 780」——只给 20 条却不说还有 760 条是误导。
     */
    private Integer trackTotal = 0;
    private Integer albumTotal = 0;
    private Integer artistTotal = 0;

    private List<TrackSearchVO> tracks = List.of();
    private List<AlbumSearchVO> albums = List.of();
    private List<ArtistSearchVO> artists = List.of();

    /**
     * 「你歌单里还没入库的」命中 —— 搜索的第二来源（2026-10-09）。
     * 库里搜不到的中文歌，往往就在这儿：「消失」变成「看得见、有状态、能试听」。
     */
    private List<MyPlaylistHitVO> playlistHits = List.of();
}
