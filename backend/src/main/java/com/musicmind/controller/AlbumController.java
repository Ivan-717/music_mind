package com.musicmind.controller;

import com.musicmind.service.AlbumService;
import com.musicmind.vo.AlbumVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

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
}
