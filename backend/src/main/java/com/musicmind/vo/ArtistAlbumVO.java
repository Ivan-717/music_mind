package com.musicmind.vo;

import lombok.Data;

import java.time.LocalDate;

/**
 * 歌手页专辑列表里的一项。
 *
 * trackCount 是【默认版本】（最早发行的那个 release）的曲目数，
 * 和专辑详情页默认显示的版本保持一致。
 * 不用「跨所有 release 去重」——那会把不同版本的曲目并起来，数字虚高。
 */
@Data
public class ArtistAlbumVO {
    private Long id;
    private String name;
    private LocalDate releaseDate;
    private String primaryType;
    private Integer trackCount;
}
