package com.musicmind.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

/**
 * 一轮对话的请求体。
 *
 * 【conversationId 可空】留空 = 新开一个会话（前端「新对话」按钮走的就是这条路）。
 * 给了就必须是本人的，否则 404。
 */
@Data
public class ChatRequest {

    private Long conversationId;

    @NotBlank(message = "消息不能为空")
    @Size(max = 500, message = "消息最长 500 字")
    private String message;
}
