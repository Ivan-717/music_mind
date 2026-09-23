package com.musicmind.controller;

import com.musicmind.security.CurrentUser;
import com.musicmind.service.FavoriteService;
import com.musicmind.vo.FavoriteTrackVO;
import com.musicmind.vo.PageVO;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/favorites")
@RequiredArgsConstructor
public class FavoriteController {

    private final FavoriteService favoriteService;

    @PostMapping("/{trackId}")
    @ResponseStatus(HttpStatus.CREATED)
    public void add(@PathVariable Long trackId) {
        favoriteService.add(CurrentUser.id(), trackId);
    }

    @DeleteMapping("/{trackId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void remove(@PathVariable Long trackId) {
        favoriteService.remove(CurrentUser.id(), trackId);
    }

    @GetMapping
    public PageVO<FavoriteTrackVO> list(@RequestParam(defaultValue = "1") int page,
                                        @RequestParam(defaultValue = "20") int size) {
        return favoriteService.list(CurrentUser.id(), page, size);
    }

    @GetMapping("/ids")
    public List<Long> ids() {
        return favoriteService.favoriteTrackIds(CurrentUser.id());
    }
}