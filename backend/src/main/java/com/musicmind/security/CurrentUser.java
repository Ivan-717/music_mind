package com.musicmind.security;

import com.musicmind.exception.ApiException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;

/**
 * 取当前登录用户 id 的统一入口。
 *
 * <p>token 由 {@code BearerTokenAuthenticationFilter} 解析并验签后放进 SecurityContext，
 * 这里只负责把它读出来。任何拿不到合法 id 的情况一律抛 401，
 * 由 {@code GlobalExceptionHandler} 统一成 ApiError 格式。
 */
public final class CurrentUser {

    private CurrentUser() {
    }

    public static Long id() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !(auth.getPrincipal() instanceof Jwt jwt)) {
            throw new ApiException(401, "未登录");
        }
        try {
            return Long.valueOf(jwt.getSubject());
        } catch (NumberFormatException e) {
            // token 签名合法但 sub 不是数字：签发端出问题，不是攻击者能构造的
            throw new ApiException(401, "token 无效");
        }
    }
}
