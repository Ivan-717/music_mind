package com.musicmind.service.imports;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.musicmind.exception.ApiException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * QQ 音乐歌单抓取。
 *
 * 走的是 fcg_ucc_getcdinfo_byids_cp.fcg —— 未加密的老接口，实测可用
 * （2026-09-30，76 首带歌手/专辑/时长）。同样不是官方开放的。
 *
 * ⚠️ 两个和网易云不一样的地方：
 *   1. 时长字段叫 interval，单位是【秒】——要乘 1000 才是毫秒
 *   2. 成功码是 code=0（网易云是 200）
 */
@Slf4j
@Component
public class QqMusicPlaylistProvider implements PlaylistProvider {

    private static final String API =
            "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
            + "?type=1&json=1&utf8=1&onlysong=0&format=json&disstid=";

    private static final Pattern PATH_ID = Pattern.compile("/playlist/(\\d+)");
    private static final Pattern PARAM_ID = Pattern.compile("[?&]disstid=(\\d+)");
    private static final Pattern BARE_ID = Pattern.compile("^\\d{3,}$");

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    private final ObjectMapper objectMapper;

    public QqMusicPlaylistProvider(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public String name() {
        return "qq";
    }

    @Override
    public boolean supports(String url) {
        return url != null && url.contains("y.qq.com");
    }

    static String extractId(String url) {
        if (url == null) {
            return null;
        }
        String trimmed = url.trim();
        if (BARE_ID.matcher(trimmed).matches()) {
            return trimmed;
        }
        Matcher m = PATH_ID.matcher(trimmed);
        if (m.find()) {
            return m.group(1);
        }
        m = PARAM_ID.matcher(trimmed);
        return m.find() ? m.group(1) : null;
    }

    @Override
    public ParsedPlaylist fetch(String url) {
        String id = extractId(url);
        if (id == null) {
            throw new ApiException(400,
                    "没能从链接里认出 QQ 音乐歌单 id，链接形如 https://y.qq.com/n/ryqq/playlist/数字");
        }

        HttpRequest request = HttpRequest.newBuilder(URI.create(API + id))
                .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
                .header("Referer", "https://y.qq.com/")
                .header("Accept", "application/json")
                .timeout(Duration.ofSeconds(20))
                .GET()
                .build();

        HttpResponse<String> response;
        try {
            response = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (IOException e) {
            throw new ApiException(502, "连不上 QQ 音乐：" + e.getMessage());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiException(502, "抓取 QQ 音乐歌单被中断");
        }

        if (response.statusCode() != 200) {
            throw new ApiException(502, "QQ 音乐返回 " + response.statusCode());
        }

        return parse(response.body(), url, id);
    }

    private ParsedPlaylist parse(String body, String url, String id) {
        JsonNode root;
        try {
            root = objectMapper.readTree(body);
        } catch (IOException e) {
            throw new ApiException(502, "QQ 音乐返回的不是 JSON（接口可能已变更或被拦截）");
        }

        // QQ 音乐的成功码是 0
        if (root.path("code").asInt(-1) != 0) {
            throw new ApiException(502, "QQ 音乐接口返回 code=" + root.path("code").asInt(-1)
                    + "（接口可能已变更，或歌单是私密的）");
        }

        JsonNode cdlist = root.path("cdlist");
        if (!cdlist.isArray() || cdlist.isEmpty()) {
            throw new ApiException(502, "QQ 音乐响应里没有 cdlist（接口可能已变更）");
        }

        JsonNode cd = cdlist.get(0);
        ParsedPlaylist playlist = new ParsedPlaylist();
        playlist.setProvider(name());
        playlist.setExternalId(id);
        playlist.setName(cd.path("dissname").asText("未命名歌单"));

        List<ParsedTrack> tracks = new ArrayList<>();
        for (JsonNode node : cd.path("songlist")) {
            String title = node.path("songname").asText("");
            String externalId = node.path("songmid").asText("");
            if (title.isEmpty() || externalId.isEmpty()) {
                continue;                       // 没歌名或没 songmid 的行没法用，跳过
            }

            ParsedTrack track = new ParsedTrack();
            track.setExternalId(externalId);
            track.setTitle(title);
            track.setAlbumName(node.path("albumname").asText(""));
            // ⚠️ QQ 音乐给的是【秒】，换成毫秒再存
            track.setDurationMs(node.path("interval").asLong(0) * 1000L);
            track.setArtists(namesOf(node.path("singer")));
            track.setCoverUrl(coverUrlOf(node.path("albummid").asText("")));
            tracks.add(track);
        }
        playlist.setTracks(tracks);

        if (tracks.isEmpty()) {
            log.warn("QQ 音乐歌单 {} 解析出 0 首，如果歌单实际有歌，多半是接口变了", url);
        }
        return playlist;
    }

    /**
     * 用 albummid 拼封面地址。QQ 音乐给的是 albummid 而不是完整 URL，
     * 要自己套模板：T002R300x300M000 + albummid。
     *
     * 拼不出就返回空串（前端会退化成不显示图），不要瞎猜一个地址。
     */
    private static String coverUrlOf(String albumMid) {
        if (albumMid == null || albumMid.isBlank()) {
            return "";
        }
        return "https://y.qq.com/music/photo_new/T002R300x300M000" + albumMid + ".jpg";
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
