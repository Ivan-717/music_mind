package com.musicmind.service;

import com.musicmind.mapper.FavoriteTrackMapper;
import com.musicmind.vo.BatchFavoriteResultVO;
import com.musicmind.vo.FavoriteTrackVO;
import com.musicmind.vo.PageVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

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

    /**
     * 批量加入收藏。
     *
     * 【不要靠 addFavorite 的返回值判断是否新增】——JDBC 默认
     * useAffectedRows=false 时，ON DUPLICATE KEY UPDATE id=id 即使没改动也返回 1。
     * 所以先一次把已有收藏拉进内存比对，准确且不依赖驱动配置。
     */
    public BatchFavoriteResultVO addBatch(Long userId, List<Long> trackIds) {
        List<Long> unique = distinct(trackIds);
        List<Long> valid = unique.isEmpty()
                ? List.of()
                : favoriteTrackMapper.selectExistingTrackIds(unique);

        Set<Long> existing = new HashSet<>(favoriteTrackMapper.selectTrackIdsByUser(userId));
        int changed = 0;
        for (Long trackId : valid) {
            if (existing.contains(trackId)) {
                continue;                       // 本来就收藏了，幂等跳过
            }
            favoriteTrackMapper.addFavorite(userId, trackId);
            existing.add(trackId);
            changed++;
        }

        BatchFavoriteResultVO vo = new BatchFavoriteResultVO();
        vo.setChanged(changed);
        vo.setUnknown(unique.size() - valid.size());
        return vo;
    }

    /** 批量取消收藏。取消不存在的收藏是空操作，不报错（和单个取消的语义一致） */
    public BatchFavoriteResultVO removeBatch(Long userId, List<Long> trackIds) {
        List<Long> unique = distinct(trackIds);
        Set<Long> existing = new HashSet<>(favoriteTrackMapper.selectTrackIdsByUser(userId));
        int changed = 0;
        for (Long trackId : unique) {
            if (!existing.contains(trackId)) {
                continue;
            }
            favoriteTrackMapper.removeFavorite(userId, trackId);
            changed++;
        }

        BatchFavoriteResultVO vo = new BatchFavoriteResultVO();
        vo.setChanged(changed);
        vo.setUnknown(0);   // 取消收藏不查 track 表：本地没有的 id 本来也删不掉，不算异常
        return vo;
    }

    /** 去重。歌单里同一首歌可能出现两次，重复操作会白跑 */
    private static List<Long> distinct(List<Long> ids) {
        return new ArrayList<>(new LinkedHashSet<>(
                ids.stream().filter(java.util.Objects::nonNull).toList()));
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