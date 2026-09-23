package com.musicmind.service;

import com.musicmind.mapper.FavoriteTrackMapper;
import com.musicmind.vo.FavoriteTrackVO;
import com.musicmind.vo.PageVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class FavoriteService {

    private final FavoriteTrackMapper favoriteTrackMapper;

    public void add(Long userId, Long trackId) {
        favoriteTrackMapper.addFavorite(userId, trackId);
    }

    public void remove(Long userId, Long trackId) {
        favoriteTrackMapper.removeFavorite(userId, trackId);
    }

    public List<Long> favoriteTrackIds(Long userId) {
        return favoriteTrackMapper.selectTrackIdsByUser(userId);
    }

    public PageVO<FavoriteTrackVO> list(Long userId, int page, int size) {
        int p = Math.max(page, 1);
        int s = Math.min(Math.max(size, 1), 100);   // 上限 100
        long total = favoriteTrackMapper.countByUser(userId);
        List<FavoriteTrackVO> items =
                favoriteTrackMapper.selectFavoritePage(userId, (p - 1) * s, s);
        PageVO<FavoriteTrackVO> vo = new PageVO<>();
        vo.setTotal(total);
        vo.setPage(p);
        vo.setSize(s);
        vo.setItems(items);
        return vo;
    }
}