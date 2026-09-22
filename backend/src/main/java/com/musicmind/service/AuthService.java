package com.musicmind.service;

import com.musicmind.dto.RegisterRequest;
import com.musicmind.entity.AppUser;
import com.musicmind.exception.ApiException;
import com.musicmind.mapper.AppUserMapper;
import com.musicmind.vo.UserVO;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;

@Service
public class AuthService {

    private final AppUserMapper appUserMapper;
    private final PasswordEncoder passwordEncoder;

    // 构造器注入，不用 @Autowired 字段注入
    public AuthService(AppUserMapper m, PasswordEncoder e) { this.appUserMapper = m; this.passwordEncoder = e; }

    public UserVO register(RegisterRequest req) {
        // ① 字节数检查 —— bcrypt 的硬约束，实测 >72 字节抛 IllegalArgumentException
        if (req.password().getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new ApiException(400, "密码过长（按 UTF-8 编码不得超过 72 字节）");
        }

        AppUser u = new AppUser();
        u.setUsername(req.username());
        u.setPasswordHash(passwordEncoder.encode(req.password()));  // 明文到此为止
        u.setNickname(req.nickname());   // 为空时兜底用 username
        u.setEmail(req.email());

        appUserMapper.insert(u);   // 撞唯一键会抛 DuplicateKeyException，交给全局处理器
        return UserVO.from(u);
    }
}

