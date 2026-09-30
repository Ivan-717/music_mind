package com.musicmind.controller;

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
