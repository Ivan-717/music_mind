package com.musicmind.service;

import com.musicmind.dto.PlaylistRequest;
import com.musicmind.entity.Playlist;
import com.musicmind.exception.ApiException;
import com.musicmind.mapper.PlaylistMapper;
import com.musicmind.vo.PlaylistTrackVO;
import com.musicmind.vo.PlaylistVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

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
