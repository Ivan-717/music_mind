package com.musicmind.controller;

import com.musicmind.security.CurrentUser;
import com.musicmind.service.EventService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/events")
@RequiredArgsConstructor
public class EventController {

    private final EventService eventService;

    /**
     * 试听上报。202 无返回体 —— 客户端 fire-and-forget，不看返回。
     * 脏数据在 service 里静默丢掉（见 EventService 的类注释）。
     */
    @PostMapping("/listen")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public void listen(@RequestBody Map<String, Object> body) {
        Long trackId = body.get("trackId") instanceof Number n ? n.longValue() : null;
        String source = body.get("source") == null ? "other" : String.valueOf(body.get("source"));
        eventService.listen(CurrentUser.id(), trackId, source);
    }
}
