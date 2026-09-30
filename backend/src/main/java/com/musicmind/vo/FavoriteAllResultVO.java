package com.musicmind.vo;

import lombok.Data;

/** 「把整个歌单加入收藏」的结果 */
@Data
public class FavoriteAllResultVO {
    /** 这次新加进去的 */
    private int added;
    /** 本来就在收藏里的 */
    private int alreadyFavorited;
    /** 还没对齐、收藏不了的 —— 这个数字必须报出来，否则用户会以为全都收藏上了 */
    private int notMatched;
}
