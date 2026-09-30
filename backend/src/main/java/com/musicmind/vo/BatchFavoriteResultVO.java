package com.musicmind.vo;

import lombok.Data;

/**
 * 批量收藏的结果。
 *
 * 【为什么不叫 added/removed】——同一个接口既可能新增也可能删除，
 * changed 一个词就够。而且要如实区分「本来就已收藏」和「本地库里根本没这首歌」：
 * 前者是正常幂等，后者说明前端传了脏 id，混在一起报数会掩盖 bug。
 */
@Data
public class BatchFavoriteResultVO {
    /** 实际发生变更的条数 */
    private int changed;
    /** 传进来的 id 里，本地 track 表没有的（已跳过） */
    private int unknown;
}
