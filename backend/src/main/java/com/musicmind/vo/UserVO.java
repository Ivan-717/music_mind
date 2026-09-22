package com.musicmind.vo;

import com.musicmind.entity.AppUser;

public record UserVO(Long id, String username, String nickname, String email) {
    public static UserVO from(AppUser u) {
        return new UserVO(u.getId(), u.getUsername(), u.getNickname(), u.getEmail());
    }
}
