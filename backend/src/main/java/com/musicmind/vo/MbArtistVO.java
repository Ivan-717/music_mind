package com.musicmind.vo;

import lombok.Data;

import java.util.List;

/**
 * MusicBrainz 歌手搜索结果的一条。
 *
 * 这不是本地库里的数据——本地没有这位歌手时才会查到这里。
 * localId 是关键的区分字段：
 *   null    → 本地还没有，需要导入
 *   非 null → 本地已经有了（用户搜的歌名/别名和本地记录对不上，但人是同一个）
 */
@Data
public class MbArtistVO {
    private String mbid;
    private String name;

    /**
     * MusicBrainz 的匹配度 0-100。⚠️ 不要拿它当相似度用：
     * 查「zzzzz不存在xyz」时每条都是 97-100 分——它是 Lucene 的相关度，
     * 查询被切词后「不存在」命中「不在」也能拿满分。过滤靠 names/aliases，不靠它。
     */
    private Integer score;

    private String country;
    private String type;            // Person / Group
    private String disambiguation;  // MusicBrainz 的消歧说明

    /** 别名（含繁简各写法、英文名）。既是过滤依据，也顺便展示给用户 */
    private List<String> aliases = List.of();

    private Long localId;
}
