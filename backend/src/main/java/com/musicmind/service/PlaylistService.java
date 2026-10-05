package com.musicmind.service;

import com.musicmind.dto.PlaylistRequest;
import com.musicmind.entity.Playlist;
import com.musicmind.exception.ApiException;
import com.musicmind.mapper.PlaylistMapper;
import com.musicmind.vo.PlaylistTrackVO;
import com.musicmind.vo.PlaylistVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class PlaylistService {

    private final PlaylistMapper playlistMapper;

    /**
     * 归属校验的唯一入口。不存在、或不属于当前用户，一律 404。
     * 不用 403 —— 那等于告诉对方「这个歌单存在，只是不归你」，泄露了存在性。
     */
    private void requireOwned(Long playlistId, Long userId) {
        if (playlistMapper.countOwned(playlistId, userId) == 0) {
            throw new ApiException(404, "歌单不存在");
        }
    }

    public List<PlaylistVO> list(Long userId) {
        return playlistMapper.selectByUser(userId);
    }

    public PlaylistVO detail(Long playlistId, Long userId) {
        requireOwned(playlistId, userId);
        return playlistMapper.selectDetail(playlistId, userId);
    }

    public PlaylistVO create(Long userId, PlaylistRequest req) {
        Playlist p = new Playlist();
        p.setUserId(userId);
        p.setName(req.getName());
        p.setDescription(req.getDescription());
        p.setIsPublic(Boolean.TRUE.equals(req.getIsPublic()));
        playlistMapper.insert(p);
        return playlistMapper.selectDetail(p.getId(), userId);
    }

    /**
     * 用一批曲目新建一张歌单 —— **一次建好并灌满**。
     *
     * 给「把 Agent 的推荐存下来」用。歌单本身是用户侧的表，归 Spring Boot 写；
     * Agent 那边只给 track_id 列表。
     */
    public Map<String, Object> createWithTracks(Long userId, String name, List<Long> trackIds) {
        Playlist p = new Playlist();
        p.setUserId(userId);
        p.setName(name);
        p.setIsPublic(false);
        playlistMapper.insert(p);

        // 先去重再查存在性。用户在对话里可能连着存两次同一批，
        // 也可能某个 track_id 在库里已经被删了
        List<Long> unique = new ArrayList<>(new LinkedHashSet<>(trackIds));
        List<Long> existing = playlistMapper.selectExistingTrackIds(unique);

        int added = 0;
        for (Long trackId : existing) {
            playlistMapper.addTrack(p.getId(), trackId);
            added++;
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", p.getId());
        out.put("name", name);
        out.put("added", added);
        out.put("skipped", unique.size() - added);
        return out;
    }

    public PlaylistVO update(Long playlistId, Long userId, PlaylistRequest req) {
        requireOwned(playlistId, userId);
        playlistMapper.update(playlistId, userId, req.getName(),
                req.getDescription(), Boolean.TRUE.equals(req.getIsPublic()));
        return playlistMapper.selectDetail(playlistId, userId);
    }

    public void delete(Long playlistId, Long userId) {
        requireOwned(playlistId, userId);
        playlistMapper.delete(playlistId, userId);
    }

    public List<PlaylistTrackVO> tracks(Long playlistId, Long userId) {
        requireOwned(playlistId, userId);
        return playlistMapper.selectTracks(playlistId);
    }

    public void addTrack(Long playlistId, Long userId, Long trackId) {
        requireOwned(playlistId, userId);
        // trackId 不存在时 insert 会抛外键异常，
        // 由 GlobalExceptionHandler 的 DataIntegrityViolationException 兜成 404
        playlistMapper.addTrack(playlistId, trackId);
    }

    public void removeTrack(Long playlistId, Long userId, Long trackId) {
        requireOwned(playlistId, userId);
        playlistMapper.removeTrack(playlistId, trackId);
    }
}
