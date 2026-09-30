package com.musicmind.vo;

import lombok.Data;

import java.util.List;

/**
 * 歌手详情。
 *
 * 注意本库的数据现实：263 个歌手里只有 7 个有别名、6 个有流派。
 * 所以 aliases / genres 大多数时候是空的，歌手页要靠 albums 撑起来
 * （95 个歌手有专辑）。
 */
@Data
public class ArtistDetailVO {
    private Long id;
    private String name;
    private String sortName;
    private String disambiguation;

    private List<String> aliases = List.of();
    private List<String> genres = List.of();

    private Integer albumCount;
    private Integer trackCount;

    private List<ArtistAlbumVO> albums = List.of();
}
