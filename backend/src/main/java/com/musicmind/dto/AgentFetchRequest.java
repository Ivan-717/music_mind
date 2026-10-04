package com.musicmind.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.List;

/**
 * 「把这个抓进库里」的请求体。来自对话页的 fetch_proposals 卡片。
 *
 * 【为什么抓取要单独一个端点，不让 Python 直接排队】
 * `ingestion_job` 归 Java 写（queue 是队列本身的一部分），而且排队有归属校验要做。
 * Python 那边只负责「查上游、给候选」，抓不抓由用户点了算。
 */
@Data
public class AgentFetchRequest {

    @NotEmpty(message = "没有指定要抓的专辑")
    @Size(max = 5, message = "一次最多抓 5 张")
    @Valid
    private List<Proposal> proposals;

    @Data
    public static class Proposal {

        /** MusicBrainz 的 release id。**由后端从上游搜索结果里来，前端只做搬运** */
        @NotBlank(message = "缺少 releaseMbid")
        private String releaseMbid;

        private String title;

        private String artist;

        /** 四位年份，可能为空 */
        private String year;

        /** 模型给的理由，只用于回显 */
        private String why;
    }
}
