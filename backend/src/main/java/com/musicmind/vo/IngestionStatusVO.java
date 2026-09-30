package com.musicmind.vo;

import lombok.Data;

import java.util.List;

/**
 * 入库队列的当前状态。前端轮询这个接口画进度面板。
 */
@Data
public class IngestionStatusVO {

    /** 用户点了「停止」。当前那条会跑完，后面的排队不动 */
    private boolean paused;

    private int queueCount;

    /** 正在跑的任务，没有则为 null */
    private Long currentJobId;

    private String currentLabel;

    /**
     * 队列里所有还活着的任务对应的曲目行 id。
     *
     * 一次性把整队列给出来，前端才能把「不在当前页」的行也标成抓取中——
     * 只靠 recentJobs 里那几条会漏。
     */
    private List<Long> activeTrackRowIds;

    private List<IngestionJobVO> recentJobs;
}
