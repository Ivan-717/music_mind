package com.musicmind.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

/** 追问的请求体 */
@Data
public class AskRequest {

    @NotNull(message = "缺少报告 id")
    private Long reportId;

    @NotBlank(message = "问题不能为空")
    @Size(max = 500, message = "问题最长 500 字")
    private String question;
}
