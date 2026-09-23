package com.musicmind.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.musicmind.dto.LoginRequest;
import com.musicmind.dto.RegisterRequest;
import com.musicmind.entity.AppUser;
import com.musicmind.exception.ApiException;
import com.musicmind.mapper.AppUserMapper;
import com.musicmind.vo.TokenVO;
import com.musicmind.vo.UserVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.temporal.ChronoUnit;

@Service
@RequiredArgsConstructor
public class AuthService {

    private final AppUserMapper appUserMapper;
    private final PasswordEncoder passwordEncoder;
    private final AuthenticationManager authenticationManager;
    private final JwtEncoder jwtEncoder;

    @Value("${JWT_EXPIRE_MINUTES}")
    private long expireMinutes;

    public UserVO register(RegisterRequest req) {
        // ① 字节数检查 —— bcrypt 的硬约束
        if (req.password().getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new ApiException(400, "密码过长（按 UTF-8 编码不得超过 72 字节）");
        }

        AppUser u = new AppUser();
        u.setUsername(req.username());
        u.setPasswordHash(passwordEncoder.encode(req.password()));
        u.setNickname(req.nickname() != null ? req.nickname() : req.username());
        u.setEmail(req.email());

        appUserMapper.insert(u);
        return UserVO.from(u);
    }

    public TokenVO login(LoginRequest req) {

        // ① 认证：失败会抛 BadCredentialsException
        Authentication auth = authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(req.username(), req.password()));

        // ② 查用户
        AppUser u = appUserMapper.selectOne(
                new LambdaQueryWrapper<AppUser>().eq(AppUser::getUsername, auth.getName()));

        // ③ 构造 claims
        Instant now = Instant.now();
        Instant exp = now.plus(expireMinutes, ChronoUnit.MINUTES);

        JwtClaimsSet claims = JwtClaimsSet.builder()
                .issuer("https://musicmind.app")
                .subject(String.valueOf(u.getId()))
                .issuedAt(now)
                .expiresAt(exp)
                .claim("username", u.getUsername())
                .build();

        // ④ 签发
        String token = jwtEncoder.encode(
                JwtEncoderParameters.from(
                        JwsHeader.with(MacAlgorithm.HS256).build(),   // ← 必须显式指定算法
                        claims)
        ).getTokenValue();


        return new TokenVO(token, "Bearer", expireMinutes * 60, UserVO.from(u));
    }

    public UserVO me(Long userId) {
        AppUser u = appUserMapper.selectById(userId);
        if (u == null) {
            throw new ApiException(401, "用户不存在");
        }
        if (u.getStatus() == null || u.getStatus() != 1) {
            throw new ApiException(401, "账号已失效");
        }
        return UserVO.from(u);
    }

}