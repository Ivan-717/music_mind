package com.musicmind.controller;

import com.musicmind.service.AlbumService;
import com.musicmind.vo.AlbumDetailVO;
import com.musicmind.vo.AlbumTrackVO;
import com.musicmind.vo.AlbumVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/albums")
@RequiredArgsConstructor
public class AlbumController {

    private final AlbumService albumService;

    @GetMapping
    public List<AlbumVO> list() {
        return albumService.listAlbums();
    }

    @GetMapping("/{id}")
    public AlbumDetailVO detail(@PathVariable Long id) {
        return albumService.detail(id);
    }

    @GetMapping("/{id}/tracks")
    public List<AlbumTrackVO> tracks(@PathVariable Long id,
                                     @RequestParam(required = false) Long releaseId) {
        return albumService.tracks(id, releaseId);
    }

}
