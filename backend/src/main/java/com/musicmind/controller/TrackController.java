package com.musicmind.controller;

import com.musicmind.service.TrackService;
import com.musicmind.vo.PreviewVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tracks")
@RequiredArgsConstructor
public class TrackController {

    private final TrackService trackService;

    /** SecurityConfig 是 anyRequest().authenticated()，这里自动要登录，不用改配置 */
    @GetMapping("/{id}/preview")
    public PreviewVO preview(@PathVariable Long id) {
        return new PreviewVO(trackService.previewUrl(id));
    }
}