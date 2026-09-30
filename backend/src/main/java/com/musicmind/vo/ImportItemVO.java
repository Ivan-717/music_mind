package com.musicmind.vo;

import lombok.Data;

/**
 * 导入结果里的一首。
 *
 * 不管匹配上没有都返回——未匹配的要如实告诉用户「本地库里还没有」，
 * 而不是悄悄吞掉。那些正是下一步「按需入库」要处理的对象。
 */
@Data
public class ImportItemVO {
    /** 外部歌单里的原始信息 */
    private String artist;
    private String title;
    private String albumName;
    private Long durationMs;

    /** 本地匹配结果。matched=false 时下面几个都是 null */
    private boolean matched;
    private Long trackId;
    private String trackName;
    private Long localAlbumId;
    private String localAlbumName;

    /** 之前就已经收藏过，本次没有新增 */
    private boolean alreadyFavorited;
}
