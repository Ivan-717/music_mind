package com.musicmind.controller;

import com.musicmind.dto.PlaylistFromTracksRequest;
import com.musicmind.dto.PlaylistRequest;
import com.musicmind.security.CurrentUser;
import com.musicmind.service.PlaylistService;
import com.musicmind.vo.PlaylistTrackVO;
import com.musicmind.vo.PlaylistVO;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/playlists")
@RequiredArgsConstructor
public class PlaylistController {

    private final PlaylistService playlistService;

    @GetMapping
    public List<PlaylistVO> list() {
        return playlistService.list(CurrentUser.id());
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public PlaylistVO create(@Valid @RequestBody PlaylistRequest req) {
        return playlistService.create(CurrentUser.id(), req);
    }

    /** 用一批曲目直接建一张歌单。给「把 Agent 的推荐存下来」用 */
    @PostMapping("/from-tracks")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> fromTracks(@Valid @RequestBody PlaylistFromTracksRequest req) {
        return playlistService.createWithTracks(CurrentUser.id(), req.getName(), req.getTrackIds());
    }

    @GetMapping("/{id}")
    public PlaylistVO detail(@PathVariable Long id) {
        return playlistService.detail(id, CurrentUser.id());
    }

    @PutMapping("/{id}")
    public PlaylistVO update(@PathVariable Long id, @Valid @RequestBody PlaylistRequest req) {
        return playlistService.update(id, CurrentUser.id(), req);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable Long id) {
        playlistService.delete(id, CurrentUser.id());
    }

    @GetMapping("/{id}/tracks")
    public List<PlaylistTrackVO> tracks(@PathVariable Long id) {
        return playlistService.tracks(id, CurrentUser.id());
    }

    @PostMapping("/{id}/tracks/{trackId}")
    @ResponseStatus(HttpStatus.CREATED)
    public void addTrack(@PathVariable Long id, @PathVariable Long trackId) {
        playlistService.addTrack(id, CurrentUser.id(), trackId);
    }

    @DeleteMapping("/{id}/tracks/{trackId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void removeTrack(@PathVariable Long id, @PathVariable Long trackId) {
        playlistService.removeTrack(id, CurrentUser.id(), trackId);
    }
}
