package com.musicmind.exception;

import com.fasterxml.jackson.annotation.JsonInclude;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record ApiError(
        int status,
        String message,
        java.util.Map<String, String> fields
) {}