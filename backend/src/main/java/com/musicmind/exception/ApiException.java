package com.musicmind.exception;

import lombok.Getter;

@Getter
public class ApiException extends RuntimeException {
    private final int status;

    public ApiException(int status, String message) {
        super(message);
        this.status = status;
    }
}