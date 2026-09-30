package com.musicmind.service.imports;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.musicmind.exception.ApiException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 网易云歌单抓取。
 *
 * 【要用两个接口，不是一个】——踩过一次的坑：
 *   /api/playlist/detail  （老接口）对官方榜单歌单会返回全部曲目，
 *                         但对普通用户歌单【只返回前 10 首】，
 *                         而它的 trackCount 字段也会跟着变成 10，
 *                         所以「看起来一切正常」，实则少了 90% 的歌。
 *
 * 正确做法是：
 *   1. /api/v6/playlist/detail  → playlist.name + playlist.trackIds（完整 ID 列表）
 *   2. /api/v3/song/detail      → 用 ID 批量换歌名/歌手/专辑/时长
 * 实测 144 首一次全量拿回，0.3 秒。
 *
 * 两个接口都不是官方开放的，随时可能变——失败时抛 502 说清可能的原因，
 * 不要返回空列表让人以为歌单本来就是空的。
 */
@Slf4j
@Component
public class NeteasePlaylistProvider implements PlaylistProvider {

    private static final String V6_API = "https://music.163.com/api/v6/playlist/detail?id=";
    private static final String V3_SONG_API = "https://music.163.com/api/v3/song/detail?c=";

    /** 一次换多少首详情。144 首的 URL 约 5KB，多数服务器 8KB 上限撑得住，
     *  但别贴着边——200 留了余量。 */
    private static final int DETAIL_BATCH_SIZE = 200;

    private static final Pattern ID_PATTERN = Pattern.compile("[?&#]id=(\\d+)");
    private static final Pattern BARE_ID = Pattern.compile("^\\d{3,}$");

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    private final ObjectMapper objectMapper;

    public NeteasePlaylistProvider(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public String name() {
        return "netease";
    }

    @Override
    public boolean supports(String url) {
        return url != null && url.contains("music.163.com");
    }

    /** 从各种形态的链接里抠出歌单 id；直接贴一串数字也认 */
    static String extractId(String url) {
        if (url == null) {
            return null;
        }
        String trimmed = url.trim();
        if (BARE_ID.matcher(trimmed).matches()) {
            return trimmed;
        }
        Matcher m = ID_PATTERN.matcher(trimmed);
        return m.find() ? m.group(1) : null;
    }

    @Override
    public ParsedPlaylist fetch(String url) {
        String id = extractId(url);
        if (id == null) {
            throw new ApiException(400,
                    "没能从链接里认出网易云歌单 id，链接形如 https://music.163.com/playlist?id=数字");
        }

        JsonNode v6 = getJson(V6_API + id + "&n=1000");
        int code = v6.path("code").asInt(-1);
        if (code != 200) {
            throw new ApiException(502, "网易云接口返回 code=" + code
                    + "（接口可能已变更，或歌单是私密的）");
        }
        JsonNode playlistNode = v6.path("playlist");
        if (playlistNode.isMissingNode() || playlistNode.isNull()) {
            throw new ApiException(502, "网易云响应里没有 playlist 节点（接口可能已变更）");
        }

        List<Long> ids = new ArrayList<>();
        for (JsonNode node : playlistNode.path("trackIds")) {
            long trackId = node.path("id").asLong(0);
            if (trackId > 0) {
                ids.add(trackId);
            }
        }
        if (ids.isEmpty()) {
            throw new ApiException(502, "这个歌单没有取到任何曲目 id（接口可能已变更，或歌单是空的）");
        }

        List<ParsedTrack> tracks = new ArrayList<>();
        for (int from = 0; from < ids.size(); from += DETAIL_BATCH_SIZE) {
            List<Long> batch = ids.subList(from, Math.min(from + DETAIL_BATCH_SIZE, ids.size()));
            tracks.addAll(fetchDetails(batch));
        }

        if (tracks.isEmpty()) {
            throw new ApiException(502, "取到了 " + ids.size() + " 个曲目 id，但一首详情都没换回来（接口可能已变更）");
        }

        ParsedPlaylist playlist = new ParsedPlaylist();
        playlist.setProvider(name());
        playlist.setExternalId(id);          // 落库去重靠它
        playlist.setName(playlistNode.path("name").asText("未命名歌单"));
        playlist.setTracks(tracks);
        log.info("网易云歌单 {} 抓到 {} 首（id 总数 {}）", id, tracks.size(), ids.size());
        return playlist;
    }

    private List<ParsedTrack> fetchDetails(List<Long> ids) {
        List<Map<String, Long>> payload = new ArrayList<>();
        for (Long trackId : ids) {
            payload.add(Map.of("id", trackId));
        }

        String encoded;
        try {
            encoded = URLEncoder.encode(objectMapper.writeValueAsString(payload), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new ApiException(500, "构造批量查询参数失败");
        }

        JsonNode root = getJson(V3_SONG_API + encoded);
        List<ParsedTrack> result = new ArrayList<>();
        for (JsonNode song : root.path("songs")) {
            String title = song.path("name").asText("");
            String externalId = String.valueOf(song.path("id").asLong(0));
            if (title.isEmpty() || "0".equals(externalId)) {
                continue;                       // 没歌名或没 id 的行没法用，跳过
            }

            ParsedTrack track = new ParsedTrack();
            track.setExternalId(externalId);
            track.setTitle(title);
            // v3 的字段是缩写的：al=album, ar=artists, dt=duration(ms)
            track.setAlbumName(song.path("al").path("name").asText(""));
            track.setDurationMs(song.path("dt").asLong(0));
            track.setArtists(namesOf(song.path("ar")));
            // 封面在 al.picUrl 里，实测可直接访问、不防盗链。
            // 只存原 URL，缩放参数（?param=100y100）交给前端按展示尺寸加。
            track.setCoverUrl(song.path("al").path("picUrl").asText(""));
            result.add(track);
        }
        return result;
    }

    private JsonNode getJson(String url) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
                .header("Referer", "https://music.163.com/")
                .header("Accept", "application/json")
                .timeout(Duration.ofSeconds(30))
                .GET()
                .build();

        HttpResponse<String> response;
        try {
            response = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new ApiException(502, "连不上网易云：" + e.getMessage());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiException(502, "抓取网易云歌单被中断");
        }

        if (response.statusCode() != 200) {
            throw new ApiException(502, "网易云返回 " + response.statusCode());
        }

        try {
            return objectMapper.readTree(response.body());
        } catch (IOException e) {
            throw new ApiException(502, "网易云返回的不是 JSON（接口可能已变更或被拦截）");
        }
    }

    private static List<String> namesOf(JsonNode array) {
        List<String> names = new ArrayList<>();
        for (JsonNode node : array) {
            String value = node.path("name").asText("");
            if (!value.isEmpty() && !names.contains(value)) {
                names.add(value);
            }
        }
        return names;
    }
}
