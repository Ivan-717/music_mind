package com.musicmind.entity;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class UserPlaylistImport {
    private Long id;
    private Long userId;
    private String provider;
    private String externalPlaylistId;
    private String playlistName;
    private String sourceUrl;
    private Integer trackCount;
    private LocalDateTime lastImportedAt;

    /**
     * 已对齐、可分析的曲目数。**不是数据库列**，只在 listImports 里由子查询算出来。
     *
     * 【为什么要它】音乐人格页的范围下拉要显示「这张歌单有多少首能分析」——
     * 只给 trackCount（歌单里有多少首）的话，用户点一张 0/76 的歌单，
     * 要等 30 秒才被告知「数据不足」。两个数差得很远是常态：814 首的
     * 「我喜欢的音乐」只有 427 首能分析。
     *
     * 其它查询（findImport / findOwnedImport）不带它，取出来是 null —— 那是预期的。
     */
    private Integer matchedCount;
}
