package com.musicmind.security;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.musicmind.entity.AppUser;
import com.musicmind.mapper.AppUserMapper;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

@Service
public class AppUserDetailsService implements UserDetailsService {

    private final AppUserMapper appUserMapper;

    public AppUserDetailsService(AppUserMapper appUserMapper) {
        this.appUserMapper = appUserMapper;
    }

    @Override
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        AppUser u = appUserMapper.selectOne(
                new LambdaQueryWrapper<AppUser>().eq(AppUser::getUsername, username));

        if (u == null) {
            throw new UsernameNotFoundException("用户不存在");
        }

        return User.withUsername(u.getUsername())
                .password(u.getPasswordHash())      // 已经是 bcrypt 串，这里不要再 encode
                .authorities("ROLE_USER")
                .disabled(u.getStatus() != 1)       // status: 0=禁用 1=正常 2=注销
                .build();
    }
}
