package com.musicmind.service;

import com.musicmind.entity.UserPlaylistImport;
import com.musicmind.entity.UserPlaylistTrack;
import com.musicmind.exception.ApiException;
import com.musicmind.mapper.FavoriteTrackMapper;
import com.musicmind.mapper.ImportMapper;
import com.musicmind.mapper.UserPlaylistMapper;
import com.musicmind.service.imports.ParsedPlaylist;
import com.musicmind.service.imports.ParsedTrack;
import com.musicmind.service.imports.PlaylistProvider;
import com.musicmind.util.KeywordVariants;
import com.musicmind.vo.FavoriteAllResultVO;
import com.musicmind.vo.ImportItemVO;
import com.musicmind.vo.ImportResultVO;
import com.musicmind.vo.ImportedPlaylistVO;
import com.musicmind.vo.TrackMatchVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class ImportService {

    private final List<PlaylistProvider> providers;
    private final ImportMapper importMapper;
    private final UserPlaylistMapper userPlaylistMapper;
    private final FavoriteTrackMapper favoriteTrackMapper;

    public ImportResultVO importPlaylist(Long userId, String url, boolean alsoFavorite) {
        PlaylistProvider provider = providers.stream()
                .filter(p -> p.supports(url))
                .findFirst()
                .orElseThrow(() -> new ApiException(400,
                        "不支持的歌单链接。目前支持网易云（music.163.com）和 QQ 音乐（y.qq.com）"));

        ParsedPlaylist playlist = provider.fetch(url);

        // ============ ① 落库：外部原始数据 ============

        UserPlaylistImport header = userPlaylistMapper.findImport(
                userId, playlist.getProvider(), playlist.getExternalId());

        if (header == null) {
            header = new UserPlaylistImport();
            header.setUserId(userId);
            header.setProvider(playlist.getProvider());
            header.setExternalPlaylistId(playlist.getExternalId());
            header.setPlaylistName(playlist.getName());
            header.setSourceUrl(url);
            header.setTrackCount(playlist.getTracks().size());
            userPlaylistMapper.insertImport(header);   // 回填 header.id
        } else {
            header.setPlaylistName(playlist.getName());
            header.setSourceUrl(url);
            header.setTrackCount(playlist.getTracks().size());
            userPlaylistMapper.updateImport(header);
        }

        List<String> keep = new ArrayList<>();
        int position = 0;

        for (ParsedTrack t : playlist.getTracks()) {
            position++;
            if (t.getExternalId() == null) continue;   // 没外部 id 没法去重，跳过
            keep.add(t.getExternalId());

            UserPlaylistTrack row = new UserPlaylistTrack();
            row.setImportId(header.getId());
            row.setUserId(userId);
            row.setProvider(playlist.getProvider());
            row.setExternalId(t.getExternalId());
            row.setPosition(position);
            row.setTitle(t.getTitle());
            row.setArtists(t.artistsText());
            row.setAlbumName(t.getAlbumName());
            row.setDurationMs(t.getDurationMs());
            row.setCoverUrl(t.getCoverUrl());
            userPlaylistMapper.upsertTrack(row);
        }

        // 歌单里被删掉的，本地也删。
        // keep 为空 = 整个歌单空了，此时要【全删】而不是跳过——
        // 跳过会让上一轮的旧歌永远留在页面上。mapper 里用 choose 分了这两支。
        userPlaylistMapper.deleteMissing(header.getId(), keep);

        // ============ ② 对齐 + 收藏 ============

        ImportResultVO result = new ImportResultVO();
        result.setProvider(playlist.getProvider());
        result.setPlaylistName(playlist.getName());
        result.setSourceUrl(url);
        result.setParsed(playlist.getTracks().size());

        // 【不要靠 addFavorite 的返回值判断是否新增】
        // JDBC 默认 useAffectedRows=false，重复插入也返回 1。
        // 一次查询把已有收藏拉进内存判断，准确且不依赖驱动配置。
        Set<Long> existing = new HashSet<>(favoriteTrackMapper.selectTrackIdsByUser(userId));

        // 上一次对齐的结果。用来做「对齐只前进不倒退」——加了时长校验之后，
        // 某些原本靠名字 + 艺人硬对上的行会被新规则拒掉，
        // 不该因为一次重导入就把用户已经能收藏的歌打回不可用
        Map<String, Long> previousMatches = new HashMap<>();
        for (Map<String, Object> row : userPlaylistMapper.selectMatchedByExternalId(header.getId())) {
            previousMatches.put(String.valueOf(row.get("externalId")),
                    ((Number) row.get("trackId")).longValue());
        }

        List<ImportItemVO> items = new ArrayList<>();
        int matched = 0;
        int added = 0;
        int already = 0;

        for (ParsedTrack track : playlist.getTracks()) {
            ImportItemVO item = new ImportItemVO();
            item.setArtist(track.artistsText());
            item.setTitle(track.getTitle());
            item.setAlbumName(track.getAlbumName());
            item.setDurationMs(track.getDurationMs());

            TrackMatchVO hit = match(track.getTitle(), track.primaryArtist(), track.getDurationMs());

            if (hit == null) {
                Long previous = previousMatches.get(track.getExternalId());
                if (previous != null) {
                    // 上次对上了、这次没对上 → 沿上次的结果走。
                    // 捞不到（那首 track 被删了）就自然退回 UNRESOLVED
                    hit = importMapper.selectTrackById(previous);
                }
            }

            // 【必须写回库】——只把结果放进返回的 item 是不够的：
            // 「我的歌单」页读的是 user_playlist_track.match_status，
            // 不写回的话那边永远是 PENDING，所有 ♡ 全禁用、收藏一首也点不动。
            userPlaylistMapper.updateMatch(
                    header.getId(),
                    track.getExternalId(),
                    hit != null ? "MATCHED" : "UNRESOLVED",
                    hit != null ? hit.getTrackId() : null);

            if (hit != null) {
                item.setMatched(true);
                item.setTrackId(hit.getTrackId());
                item.setTrackName(hit.getTrackName());
                item.setLocalAlbumId(hit.getAlbumId());
                item.setLocalAlbumName(hit.getAlbumName());
                matched++;

                // 只有用户勾了「同时加入收藏」才动收藏表。
                // 默认不动——导入是搬列表，收藏是表态，两件事。
                if (alsoFavorite) {
                    if (existing.contains(hit.getTrackId())) {
                        already++;
                        item.setAlreadyFavorited(true);
                    } else {
                        favoriteTrackMapper.addFavorite(userId, hit.getTrackId());
                        existing.add(hit.getTrackId());   // 歌单里同一首歌可能出现两次
                        added++;
                    }
                }
            }
            items.add(item);
        }

        result.setMatched(matched);
        result.setAdded(added);
        result.setAlreadyFavorited(already);
        result.setItems(items);
        return result;
    }

    // ============================================================
    // 查询：导入歌单的展示
    // ============================================================

    /** 我导入过的歌单列表 */
    public List<UserPlaylistImport> listImports(Long userId) {
        return userPlaylistMapper.listImports(userId);
    }

    /**
     * 某个导入歌单的曲目（分页）。
     *
     * 【必须先校验归属】——importId 是自增数字，别人猜一个就能读到别人的歌单。
     * 前端不显示入口不等于安全。查不到（不属于本人）就 404。
     */
    public ImportedPlaylistVO tracks(Long userId, Long importId, int page, int size, String filter) {
        UserPlaylistImport header = userPlaylistMapper.findOwnedImport(importId, userId);
        if (header == null) {
            throw new ApiException(404, "歌单不存在");
        }

        int safePage = Math.max(page, 1);
        int safeSize = Math.min(Math.max(size, 1), 200);   // 上限 200，别让人一次拉爆
        String safeFilter = normalizeFilter(filter);

        ImportedPlaylistVO vo = new ImportedPlaylistVO();
        vo.setImportId(header.getId());
        vo.setProvider(header.getProvider());
        vo.setPlaylistName(header.getPlaylistName());
        vo.setSourceUrl(header.getSourceUrl());
        vo.setLastImportedAt(header.getLastImportedAt());
        vo.setPage(safePage);
        vo.setSize(safeSize);
        vo.setFilter(safeFilter);
        // total 跟着筛选走（页码要按筛选后的总数算），但下面三个计数【始终是全量】——
        // 筛到「已收录」时还得看得见「未收录 194」才知道还剩多少要抓
        vo.setTotal(userPlaylistMapper.countTracks(importId, safeFilter));
        vo.setItems(userPlaylistMapper.selectTracks(
                importId, (safePage - 1) * safeSize, safeSize, safeFilter));

        // 各状态计数。SQL 返回的是 {matchStatus, cnt} 两列，
        // 没出现过的状态视为 0——不能因为「没有 UNRESOLVED 行」就不显示那一格。
        int matched = 0;
        int pending = 0;
        int unresolved = 0;
        for (Map<String, Object> row : userPlaylistMapper.countByStatus(importId)) {
            String status = String.valueOf(row.get("matchStatus"));
            int cnt = ((Number) row.get("cnt")).intValue();
            switch (status) {
                case "MATCHED" -> matched = cnt;
                case "UNRESOLVED" -> unresolved = cnt;
                default -> pending += cnt;          // PENDING 及任何未知状态都算待处理
            }
        }
        vo.setMatchedCount(matched);
        vo.setPendingCount(pending);
        vo.setUnresolvedCount(unresolved);
        return vo;
    }

    /** 认不出的筛选值一律当「全部」——不要为了一个拼错的参数报 400 打断用户 */
    private static String normalizeFilter(String filter) {
        return "matched".equals(filter) || "unmatched".equals(filter) ? filter : "all";
    }

    // ============================================================
    // 修改：删歌单 / 剔歌曲 / 批量收藏
    //
    // 这三件事都【不碰 favorite_track】——收藏是用户对歌的表态，
    // 歌单只是他从别处搬来的一份列表。耦合在一起的话，
    // 「删歌单要不要顺手取消收藏」永远选不对。
    // ============================================================

    /** 删掉整个导入歌单。里面被剔除过的行也一并清掉（靠外键 CASCADE） */
    public void deleteImport(Long userId, Long importId) {
        if (userPlaylistMapper.deleteImport(importId, userId) == 0) {
            throw new ApiException(404, "歌单不存在");
        }
    }

    /** 从歌单里剔除一首。软删除，下次重新导入不会复活 */
    public void removeTrack(Long userId, Long importId, Long trackRowId) {
        if (userPlaylistMapper.findOwnedImport(importId, userId) == null) {
            throw new ApiException(404, "歌单不存在");
        }
        if (userPlaylistMapper.markRemoved(importId, trackRowId) == 0) {
            throw new ApiException(404, "这首歌不在这个歌单里");
        }
    }

    /**
     * 把歌单里已对齐的歌全部加进收藏。
     *
     * 【不要靠 addFavorite 的返回值判断新增】——还是那个 JDBC 的坑：
     * useAffectedRows=false 时 ON DUPLICATE KEY UPDATE 也返回 1。
     * 一次查出已有收藏在内存里比，准确且不依赖驱动配置。
     */
    public FavoriteAllResultVO favoriteAll(Long userId, Long importId) {
        if (userPlaylistMapper.findOwnedImport(importId, userId) == null) {
            throw new ApiException(404, "歌单不存在");
        }

        List<Long> trackIds = userPlaylistMapper.selectMatchedTrackIds(importId);
        Set<Long> existing = new HashSet<>(favoriteTrackMapper.selectTrackIdsByUser(userId));

        int added = 0;
        int already = 0;
        for (Long trackId : trackIds) {
            if (existing.contains(trackId)) {
                already++;
            } else {
                favoriteTrackMapper.addFavorite(userId, trackId);
                existing.add(trackId);
                added++;
            }
        }

        FavoriteAllResultVO vo = new FavoriteAllResultVO();
        vo.setAdded(added);
        vo.setAlreadyFavorited(already);
        // 这个数字必须报出来，否则用户会以为整单都收藏上了
        vo.setNotMatched(userPlaylistMapper.countTracks(importId, "all") - trackIds.size());
        return vo;
    }

    /**
     * 拿外部的一首歌去本地库找对应曲目。找不到返回 null。
     *
     * 【参数是散的，不是 ParsedTrack】——按需入库的 worker 也要用它，
     * 但那时候手里只有 user_playlist_track 里的几个字段，拼不出 ParsedTrack。
     * 传原始值比为了复用硬造一个对象干净。
     */
    public TrackMatchVO match(String title, String artist, Long durationMs) {
        if (title == null || title.isBlank() || artist == null || artist.isBlank()) {
            return null;
        }

        List<String> titleVariants = KeywordVariants.of(title);
        List<String> artistVariants = KeywordVariants.of(artist);
        if (titleVariants.isEmpty() || artistVariants.isEmpty()) {
            return null;
        }

        return importMapper.matchTrack(
                KeywordVariants.at(titleVariants, 0),
                KeywordVariants.at(titleVariants, 1),
                KeywordVariants.at(titleVariants, 2),
                KeywordVariants.at(artistVariants, 0),
                KeywordVariants.at(artistVariants, 1),
                KeywordVariants.at(artistVariants, 2),
                durationMs);
    }
}