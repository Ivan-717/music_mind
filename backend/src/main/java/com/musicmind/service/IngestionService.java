package com.musicmind.service;

import com.musicmind.config.IngestionProperties;
import com.musicmind.dto.AgentFetchRequest;
import com.musicmind.entity.IngestionJob;
import com.musicmind.entity.UserPlaylistImport;
import com.musicmind.entity.UserPlaylistTrack;
import com.musicmind.exception.ApiException;
import com.musicmind.mapper.IngestionJobMapper;
import com.musicmind.mapper.UserPlaylistMapper;
import com.musicmind.util.ArtistText;
import com.musicmind.vo.IngestionJobVO;
import com.musicmind.vo.IngestionQueueResultVO;
import com.musicmind.vo.IngestionStatusVO;
import com.musicmind.vo.TrackMatchVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

/**
 * 按需入库（③）的排队与查询。真正干活的是 IngestionWorker。
 *
 * 【为什么是队列不是同步抓】一次入库约 7 秒，整单几百首要几十分钟。
 * 在 HTTP 线程里同步做，用户只会看到转圈直到超时。
 *
 * 【队列全局共享】——入库产物写进所有人共用的音乐侧表，
 * 所以不按用户隔离队列，只按用户校验「你能不能排这一行」。
 */
@Service
@RequiredArgsConstructor
public class IngestionService {

    /** 一次最多排多少首。每首都要现场试一次对齐，不设上限的话误点整单会把接口拖住 */
    private static final int MAX_BATCH = 500;

    /**
     * 每首的估算耗时（秒），只用于给用户一个数量级。
     *
     * 取 4 而不是实测冷启动的 6~7：歌单里同一张专辑往往有好几首，
     * 第一首才要真的走网络（搜录音 + 查 release ≈ 2s）和子进程（≈ 1.4s），
     * 后面同专辑、以及已经被别的任务重匹配解决掉的，都是几十毫秒。
     * 拿 7 去乘会把预估夸大一倍多（726 首报成 85 分钟，实际约 35）。
     */
    private static final int SECONDS_PER_TRACK = 4;

    private final IngestionJobMapper jobMapper;
    private final UserPlaylistMapper userPlaylistMapper;
    private final ImportService importService;
    private final IngestionWorker worker;
    private final IngestionProperties props;

    // ============================================================
    // 排队
    // ============================================================

    /** 逐首入库。trackRowIds 里的每一行都要属于当前用户，否则 404 */
    public IngestionQueueResultVO queueTracks(Long userId, List<Long> trackRowIds) {
        if (trackRowIds == null || trackRowIds.isEmpty()) {
            throw new ApiException(400, "没有指定要入库的曲目");
        }
        // 去重：同一行点两次不该排两条
        LinkedHashSet<Long> unique = new LinkedHashSet<>(trackRowIds);
        if (unique.size() > MAX_BATCH) {
            throw new ApiException(400, "一次最多排队 " + MAX_BATCH + " 首");
        }

        List<UserPlaylistTrack> rows = new ArrayList<>();
        for (Long id : unique) {
            // 归属校验在这里：查不到（不是自己的 / 已剔除 / 不存在）一律 404，
            // 不能让别人的 trackRowId 把任务排到别人的歌单上
            UserPlaylistTrack row = userPlaylistMapper.findTrackRow(id, userId);
            if (row == null) {
                throw new ApiException(404, "曲目不存在");
            }
            rows.add(row);
        }
        return enqueue(userId, rows);
    }

    /** 整单入库：这个歌单里所有还没对齐的曲目 */
    // 「AI 帮你找的」那张歌单。一个用户一张，抓的都往里追加 ——
    // 这样用户看得见「我让 AI 找过什么」，而且现成的浏览 / 试听 / 一键收藏都能用
    private static final String AGENT_PROVIDER = "agent";
    private static final String AGENT_PLAYLIST_ID = "agent-fetch";
    private static final String AGENT_PLAYLIST_NAME = "AI 帮你找的";

    /**
     * Agent 提议的专辑，抓进库。
     *
     * 【和 queueTracks 的区别】那边是从用户歌单的一行出发，worker 要去
     * MusicBrainz 搜录音、挑 release —— 因为那时还不知道该抓哪张。
     * 这里**已经知道 release MBID 了**（Agent 从上游搜的），所以直接把
     * `album_name` 填成 mbid：`IngestionWorker.process()` 看到
     * album_name 非空就跳过搜索直接抓。
     *
     * 副作用是**省一次 MusicBrainz 请求** —— 而且避免了「搜出来挑了另一张版本」。
     */
    public Map<String, Object> queueAgentFetch(Long userId, List<AgentFetchRequest.Proposal> proposals) {
        Long importId = ensureAgentImport(userId);

        int queued = 0;
        int skipped = 0;
        for (AgentFetchRequest.Proposal p : proposals) {
            String artist = p.getArtist() == null || p.getArtist().isBlank() ? "未知" : p.getArtist();
            String title = p.getTitle() == null || p.getTitle().isBlank() ? p.getReleaseMbid() : p.getTitle();

            UserPlaylistTrack row = new UserPlaylistTrack();
            row.setImportId(importId);
            row.setUserId(userId);
            row.setProvider(AGENT_PROVIDER);
            // external_id 用 release mbid：同一张抓两次不会产生第二行
            row.setExternalId(p.getReleaseMbid());
            row.setPosition(0);
            row.setTitle(title);
            row.setArtists(artist);
            row.setAlbumName(title);
            userPlaylistMapper.upsertTrack(row);

            UserPlaylistTrack saved =
                    userPlaylistMapper.findTrackRowByExternalId(importId, p.getReleaseMbid());
            if (saved == null) {
                continue;          // 理论上不会
            }

            // 同一张别重复排。复用现有的「歌手 + 歌名」去重，不另加一个按 release 的查询
            if (jobMapper.countActiveByArtistTitle(artist, title) > 0) {
                skipped++;
                continue;
            }

            IngestionJob job = new IngestionJob();
            job.setUserId(userId);
            job.setTrackRowId(saved.getId());
            job.setArtistName(artist);
            job.setTitle(title);
            job.setAlbumName(title);
            // 【这一行是关键】release_mbid 一填，worker 就跳过「搜录音 → 挑 release」
            // 直接抓这一张。别把它塞进 album_name —— 那个字段是
            // 「同一专辑别的歌解析过没有」的复用线索，不是「就是这张」
            job.setReleaseMbid(p.getReleaseMbid());
            jobMapper.insert(job);
            queued++;
        }

        int queueCount = jobMapper.countQueued();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("queued", queued);
        out.put("skippedQueued", skipped);
        out.put("queueCount", queueCount);
        out.put("importId", importId);
        out.put("estimateSeconds", queueCount * SECONDS_PER_TRACK);
        return out;
    }

    /** 找到或新建「AI 帮你找的」。唯一键是 (user_id, provider, external_playlist_id) */
    private Long ensureAgentImport(Long userId) {
        UserPlaylistImport found =
                userPlaylistMapper.findImport(userId, AGENT_PROVIDER, AGENT_PLAYLIST_ID);
        if (found != null) {
            return found.getId();
        }
        UserPlaylistImport row = new UserPlaylistImport();
        row.setUserId(userId);
        row.setProvider(AGENT_PROVIDER);
        row.setExternalPlaylistId(AGENT_PLAYLIST_ID);
        row.setPlaylistName(AGENT_PLAYLIST_NAME);
        row.setTrackCount(0);
        userPlaylistMapper.insertImport(row);
        return row.getId();
    }

    public IngestionQueueResultVO queueImport(Long userId, Long importId) {
        UserPlaylistImport header = userPlaylistMapper.findOwnedImport(importId, userId);
        if (header == null) {
            throw new ApiException(404, "歌单不存在");
        }
        return enqueue(userId, userPlaylistMapper.selectNotMatchedByImport(importId));
    }

    private IngestionQueueResultVO enqueue(Long userId, List<UserPlaylistTrack> rows) {
        IngestionQueueResultVO result = new IngestionQueueResultVO();
        result.setTotal(rows.size());

        int queued = 0;
        int alreadyMatched = 0;
        int alreadyQueued = 0;
        int invalid = 0;

        for (UserPlaylistTrack row : rows) {
            String artist = ArtistText.primary(row.getArtists());
            if (row.getTitle() == null || row.getTitle().isBlank() || artist == null) {
                invalid++;
                continue;
            }

            // 【现场再试一次对齐】——队列是全局共享的，别人可能刚把这张专辑抓进来。
            // 不试的话会把已经能收藏的歌白排一轮（还要等好几分钟才知道是白排）
            TrackMatchVO hit = importService.match(row.getTitle(), artist, row.getDurationMs());
            if (hit != null) {
                userPlaylistMapper.updateMatch(
                        row.getImportId(), row.getExternalId(), "MATCHED", hit.getTrackId());
                alreadyMatched++;
                continue;
            }

            // 两道去重：先按行（同一行连点），再按「歌手 + 歌名」（不同歌单里的同一首歌）
            if (jobMapper.countActiveByTrackRow(row.getId()) > 0
                    || jobMapper.countActiveByArtistTitle(artist, row.getTitle()) > 0) {
                alreadyQueued++;
                continue;
            }

            IngestionJob job = new IngestionJob();
            job.setUserId(userId);
            job.setTrackRowId(row.getId());
            job.setArtistName(artist);
            job.setTitle(row.getTitle());
            job.setAlbumName(row.getAlbumName());
            job.setDurationMs(row.getDurationMs());
            jobMapper.insert(job);
            queued++;
        }

        int queueCount = jobMapper.countQueued();

        result.setQueued(queued);
        result.setSkippedAlreadyMatched(alreadyMatched);
        result.setSkippedQueued(alreadyQueued);
        result.setSkippedInvalid(invalid);
        result.setQueueCount(queueCount);
        result.setEstimateSeconds(queueCount * SECONDS_PER_TRACK);
        return result;
    }

    // ============================================================
    // 状态 / 暂停
    // ============================================================

    public IngestionStatusVO status() {
        IngestionStatusVO vo = new IngestionStatusVO();
        vo.setPaused(worker.isPaused());
        vo.setQueueCount(jobMapper.countQueued());
        vo.setCurrentJobId(worker.getCurrentJobId());
        vo.setCurrentLabel(worker.getCurrentLabel());
        vo.setActiveTrackRowIds(jobMapper.selectActiveTrackRowIds());

        List<IngestionJobVO> jobs = new ArrayList<>();
        for (IngestionJob job : jobMapper.recent(props.getRecentJobs())) {
            IngestionJobVO item = new IngestionJobVO();
            item.setId(job.getId());
            item.setTrackRowId(job.getTrackRowId());
            item.setArtistName(job.getArtistName());
            item.setTitle(job.getTitle());
            item.setAlbumName(job.getAlbumName());
            item.setReleaseMbid(job.getReleaseMbid());
            item.setStatus(job.getStatus());
            item.setRematchedCount(job.getRematchedCount());
            item.setErrorMessage(job.getErrorMessage());
            item.setStartedAt(job.getStartedAt());
            item.setFinishedAt(job.getFinishedAt());
            jobs.add(item);
        }
        vo.setRecentJobs(jobs);
        return vo;
    }

    /** 当前这条跑完就停，队列保留 */
    public void stop() {
        worker.pause();
    }

    public void resume() {
        worker.resume();
    }
}
