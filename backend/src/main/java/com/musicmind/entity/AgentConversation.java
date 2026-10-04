package com.musicmind.entity;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 一个对话会话。
 *
 * 【为什么要有它】「针对某份报告的追问」锚定的是报告；「自由问答」没有报告可锚，
 * 得有自己的容器。两者共用 `agent_message`，靠挂在哪一列上区分。
 *
 * 存在的理由只有一个：**让插入能回填自增 id**（`@Options(useGeneratedKeys)`）。
 * 查询一律返回 Map —— 和报告那条线一样，这一层不抄 schema。
 */
@Data
public class AgentConversation {

    private Long id;

    private Long userId;

    /** 列表页显示用。取第一句的前 20 字 */
    private String title;

    private LocalDateTime createdAt;
}
