package com.musicmind.vo;

import lombok.Data;

/**
 * MusicBrainz 上挑中的那个 release —— 按需入库的「原料」。
 *
 * 只有 mbid 是必须的（Python 子进程靠它抓整张专辑），
 * 其余字段都是给日志和失败提示用的：用户看到「抓的是《范特西》2001 版」
 * 才能判断挑得对不对。
 */
@Data
public class MbReleaseCandidateVO {

    /** MusicBrainz release MBID，传给 ingest_release.py 的就是它 */
    private String mbid;

    private String title;

    /** 艺人名。release 的 artist-credit 可能没返回，允许为 null */
    private String artist;

    /** 发行日期，MB 里可能是 "2001" 也可能是 "2001-09-14" */
    private String date;

    /** Official / Bootleg / Promotion…… */
    private String status;

    /** release-group 的 primary-type：Album / EP / Single…… */
    private String primaryType;

    private String releaseGroupTitle;
}
