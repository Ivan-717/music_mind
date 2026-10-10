package com.musicmind.vo;

import lombok.Data;

/**
 * 排队结果。各字段分开报，是为了让用户知道「点了 30 首，为什么只排进去 12 首」。
 */
@Data
public class IngestionQueueResultVO {

    /** 提交上来的行数 */
    private int total;

    /** 真正排进队列的 */
    private int queued;

    /** 现场一试就对上、不用入库的（别人可能刚抓过同一张专辑） */
    private int skippedAlreadyMatched;

    /** 队列里已经有同一首了（同一行，或别的歌单里同歌手的同一首歌） */
    private int skippedQueued;

    /** 歌名或歌手是空的，没法查（脏数据） */
    private int skippedInvalid;

    /** 之前确认过 MusicBrainz 上没有（NOT_FOUND 的历史任务）—— 不白排，如实告诉用户 */
    private int skippedNotFound;

    /** 排完之后队列总长 */
    private int queueCount;

    /** 估算耗时（秒）。按每首约 7 秒算：搜索 1s + 查 releases 1s + 子进程 2s + 写库 1s + 限速余量 */
    private int estimateSeconds;
}
