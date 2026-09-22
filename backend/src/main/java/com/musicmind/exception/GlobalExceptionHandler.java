package com.musicmind.exception;

import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.*;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

import java.util.HashMap;
import java.util.Map;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    // ① 参数校验失败 → 400
    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(
            MethodArgumentNotValidException ex,
            HttpHeaders headers,
            HttpStatusCode status,
            WebRequest request) {

        Map<String, String> fields = new HashMap<>();
        for (FieldError fieldError : ex.getBindingResult().getFieldErrors()) {
            fields.putIfAbsent(fieldError.getField(), fieldError.getDefaultMessage());
        }

        return ResponseEntity.badRequest()
                .body(new ApiError(400, "参数校验失败", fields));
    }

    // ② 唯一键冲突 → 409
    @ExceptionHandler(DuplicateKeyException.class)
    public ResponseEntity<ApiError> handleDuplicateKey(DuplicateKeyException ex) {
        String msg = ex.getMessage();
        String message;

        if (msg != null && msg.contains("uk_app_user_username")) {
            message = "用户名已被占用";
        } else if (msg != null && msg.contains("uk_app_user_email")) {
            message = "邮箱已被占用";
        } else {
            message = "数据已存在";
        }

        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(new ApiError(409, message, null));
    }

    // ③ 自定义业务异常 → 用它自带的状态码
    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ApiError> handleApiException(ApiException ex) {
        return ResponseEntity.status(ex.getStatus())
                .body(new ApiError(ex.getStatus(), ex.getMessage(), null));
    }

    // ④ 兜底 → 500
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> handleException(Exception ex) {
        log.error("未预期异常", ex);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(new ApiError(500, "服务器内部错误", null));
    }

    // ⑤ Spring MVC 的 20 个异常统一格式
    @Override
    protected ResponseEntity<Object> handleExceptionInternal(
            Exception ex, Object body, HttpHeaders headers,
            HttpStatusCode statusCode, WebRequest request) {

        String message;
        if (body instanceof ProblemDetail pd && pd.getDetail() != null) {
            message = pd.getDetail();
        } else {
            HttpStatus s = HttpStatus.resolve(statusCode.value());
            message = (s != null) ? s.getReasonPhrase() : "请求处理失败";
        }

        return super.handleExceptionInternal(
                ex,
                new ApiError(statusCode.value(), message, null),
                headers, statusCode, request);
    }
}