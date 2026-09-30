package com.musicmind.controller;

import com.musicmind.dto.BatchFavoriteRequest;
import com.musicmind.security.CurrentUser;
import com.musicmind.service.FavoriteService;
import com.musicmind.vo.BatchFavoriteResultVO;
import com.musicmind.vo.FavoriteTrackVO;
import com.musicmind.vo.PageVO;
import jakarta.validation.Valid;
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

    /**
     * 批量加入收藏。
     *
     * 路径 /batch 和上面的 /{trackId} 不冲突：Spring 的字面量路径优先于模板变量，
     * 所以 POST /api/favorites/batch 不会被当成 trackId="batch"。
     */
    @PostMapping("/batch")
    public BatchFavoriteResultVO addBatch(@Valid @RequestBody BatchFavoriteRequest request) {
        return favoriteService.addBatch(CurrentUser.id(), request.getTrackIds());
    }

    /**
     * 批量取消收藏。
     *
     * 【为什么是 POST 而不是 DELETE 带 body】DELETE 请求体在 HTTP 里语义模糊，
     * 代理和部分客户端会直接丢掉，用 POST 才稳。
     */
    @PostMapping("/batch/remove")
    public BatchFavoriteResultVO removeBatch(@Valid @RequestBody BatchFavoriteRequest request) {
        return favoriteService.removeBatch(CurrentUser.id(), request.getTrackIds());
    }
}