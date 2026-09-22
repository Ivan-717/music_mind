package com.musicmind.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record RegisterRequest(
        @NotBlank(message = "用户名不能为空")
        @Size(min = 3, max = 32, message = "用户名长度需在 3-32 之间")
        @Pattern(regexp = "^[a-zA-Z0-9_]+$", message = "用户名只能包含字母、数字、下划线")
        String username,

        @NotBlank(message = "密码不能为空")
        @Size(min = 8, max = 72, message = "密码长度需在 8-72 之间")
        String password,

        @Size(max = 64, message = "昵称最长 64 字符")
        String nickname,

        @Email(message = "邮箱格式不正确")
        @Size(max = 255)
        String email
) {}
