package com.musicmind.controller;

import com.musicmind.dto.RegisterRequest;
import com.musicmind.service.AuthService;
import com.musicmind.vo.UserVO;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/register")
    @ResponseStatus(HttpStatus.CREATED)
    public UserVO register(@Valid @RequestBody RegisterRequest req) {
        return authService.register(req);
    }
}

