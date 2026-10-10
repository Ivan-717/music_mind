package com.musicmind.controller;

import com.musicmind.dto.IngestionTracksRequest;
import com.musicmind.security.CurrentUser;
import com.musicmind.service.IngestionService;
import com.musicmind.vo.IngestionQueueResultVO;
import com.musicmind.vo.IngestionStatusVO;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 按需入库（③）。
 *
 * 【权限不用额外配】SecurityConfig 只放行了 login / register，
 * 其余 anyRequest().authenticated()，这几个端点自动受 JWT 保护。
 *
 * 这条路径不做音乐侧表的写操作——写库是 Python 管道的活，
 * 这里只负责解析、排队、和入库后的重新对齐。
 */
@RestController
@RequestMapping("/api/ingestion")
@RequiredArgsConstructor
public class IngestionController {

    private final IngestionService ingestionService;

    /**
     * 逐首入库。
     *
     * 返回 202 而不是 200：这里是「已受理」，抓取还在后台排队，
     * 进度得靠 GET /status 轮询。
     */
    @PostMapping("/tracks")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public IngestionQueueResultVO queueTracks(@RequestBody IngestionTracksRequest req) {
        return ingestionService.queueTracks(CurrentUser.id(), req.getTrackRowIds());
    }

    /**
     * 「补全这位歌手的专辑」（搜索页的入口，2026-10-09）。
     *
     * body: {mbid} 或 {artistId} —— 上游 lookup 的条目带 mbid，本地搜索的条目只有 id。
     * artistName 可选，只用于歌单行标题（抓取本身只认 mbid）。
     * 返回 {queued, skippedQueued, found, estimateSeconds, importId}；
     * **found 可能是 0**（没有可补的专辑），前端要如实显示。
     */
    @PostMapping("/artist")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> queueArtist(@RequestBody Map<String, Object> body) {
        String mbid = body.get("mbid") == null ? null : String.valueOf(body.get("mbid"));
        Long artistId = body.get("artistId") instanceof Number n ? n.longValue() : null;
        String name = body.get("artistName") == null ? null : String.valueOf(body.get("artistName"));
        return ingestionService.queueArtist(CurrentUser.id(), mbid, artistId, name);
    }

    /** 整单入库：这个歌单里所有还没对齐的曲目 */
    @PostMapping("/playlists/{importId}")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public IngestionQueueResultVO queuePlaylist(@PathVariable Long importId) {
        return ingestionService.queueImport(CurrentUser.id(), importId);
    }

    /** 队列状态。前端轮询这个画进度面板 */
    @GetMapping("/status")
    public IngestionStatusVO status() {
        return ingestionService.status();
    }

    /** 停止。当前那条跑完即停，队列保留 */
    @PostMapping("/stop")
    public IngestionStatusVO stop() {
        ingestionService.stop();
        return ingestionService.status();
    }

    @PostMapping("/resume")
    public IngestionStatusVO resume() {
        ingestionService.resume();
        return ingestionService.status();
    }
}
