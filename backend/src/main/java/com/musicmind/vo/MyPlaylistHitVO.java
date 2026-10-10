package com.musicmind.vo;

import lombok.Data;

/**
 * 「我歌单里、但还没入库」的一行 —— 搜索结果的第二来源（2026-10-09）。
 *
 * 【为什么加它】MusicBrainz 对中文流行/说唱覆盖很差，用户歌单里近一半的歌
 * 对齐不上、库里搜不到 —— 但**它们其实已经在导入的歌单里躺着**（歌名/艺人/
 * 时长/封面/网易云 id 全都有）。搜索并上这一来源之后，「搜不到」变成
 * 「搜得到、看得见状态」，未入库的还能直接试听（网易云外链）。
 */
@Data
public class MyPlaylistHitVO {
    /** user_playlist_track.id —— 去歌单页定位/后续操作都用它 */
    private Long rowId;
    private Long importId;
    /** 在哪张歌单里（前端显示「在『我喜欢的音乐』里」） */
    private String playlistName;
    /** netease / qq / agent —— 只有 netease 有公开试听外链 */
    private String provider;
    /** 网易云的 song id（试听外链就靠它） */
    private String externalId;
    private String title;
    private String artists;
    private String albumName;
    private Long durationMs;
    private String coverUrl;
    /** PENDING（识别中）/ UNRESOLVED（确认对不上） */
    private String matchStatus;
}
