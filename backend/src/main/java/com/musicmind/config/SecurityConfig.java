package com.musicmind.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
                // 无状态 JWT 方案，不依赖 Cookie，CSRF 攻击面不存在
                .csrf(csrf -> csrf.disable())
                // 不要 Spring 自带的登录页和 Basic 弹窗，认证由 JWT 过滤器负责
                .formLogin(form -> form.disable())
                .httpBasic(basic -> basic.disable())
                // 不创建 HttpSession，每个请求自带 JWT
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                // 【临时】现在全部放行。Step 4 会改成 /api/auth/** 放行、其余要认证
                .authorizeHttpRequests(auth -> auth.anyRequest().permitAll());

        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        // Step 2 注册时用它加密，Step 3 登录时用它比对
        return new BCryptPasswordEncoder();
    }
}
