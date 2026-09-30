package com.musicmind.controller;

import com.musicmind.dto.ImportRequest;
import com.musicmind.entity.UserPlaylistImport;
import com.musicmind.security.CurrentUser;
import com.musicmind.service.ImportService;
import com.musicmind.vo.FavoriteAllResultVO;
import com.musicmind.vo.ImportResultVO;
import com.musicmind.vo.ImportedPlaylistVO;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/import")
@RequiredArgsConstructor
public class ImportController {

    private final ImportService importService;

    /**
     * 导入一个外部歌单。
     *
     * 目前【只匹配本地已有的】，不做抓取入库——那一步在之后。
     * 所以返回里的 unmatched 数量会明显大于 0，这是如实反映覆盖率，
     * 不是失败。
     */
    @PostMapping("/playlist")
    public ImportResultVO importPlaylist(@Valid @RequestBody ImportRequest request) {
        return importService.importPlaylist(
                CurrentUser.id(), request.getUrl(), request.isFavorite());
    }

    /** 我的导入歌单列表 */
    @GetMapping("/playlists")
    public List<UserPlaylistImport> playlists() {
        return importService.listImports(CurrentUser.id());
    }

    /** 某个导入歌单的曲目（分页） */
    @GetMapping("/playlists/{importId}/tracks")
    public ImportedPlaylistVO tracks(@PathVariable Long importId,
                                     @RequestParam(defaultValue = "1") int page,
                                     @RequestParam(defaultValue = "50") int size,
                                     @RequestParam(defaultValue = "all") String filter) {
        return importService.tracks(CurrentUser.id(), importId, page, size, filter);
    }

    /** 删掉整个导入歌单。里面的曲目靠外键级联清掉，收藏不受影响 */
    @DeleteMapping("/playlists/{importId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deletePlaylist(@PathVariable Long importId) {
        importService.deleteImport(CurrentUser.id(), importId);
    }

    /** 从歌单里剔除一首歌。软删除，重新导入也不会复活，收藏不受影响 */
    @DeleteMapping("/playlists/{importId}/tracks/{trackId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void removeTrack(@PathVariable Long importId, @PathVariable Long trackId) {
        importService.removeTrack(CurrentUser.id(), importId, trackId);
    }

    /** 把歌单里已对齐的歌全部加进收藏（不用逐首勾，一键整单） */
    @PostMapping("/playlists/{importId}/favorite-all")
    public FavoriteAllResultVO favoriteAll(@PathVariable Long importId) {
        return importService.favoriteAll(CurrentUser.id(), importId);
    }

}
