package com.musicmind.vo;

public record TokenVO(String token, String tokenType, long expiresIn, UserVO user) {}