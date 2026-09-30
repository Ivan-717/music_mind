package com.musicmind.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.musicmind.exception.ApiException;
import com.musicmind.mapper.ArtistMapper;
import com.musicmind.util.KeywordVariants;
import com.musicmind.vo.MbArtistVO;
import com.musicmind.vo.MbReleaseCandidateVO;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * 查 MusicBrainz —— 只用于「本地没有这位歌手」时告诉用户上游有什么。
 *
 * 【本类不做导入】。抓取入库是 Python 管道的活（data-pipeline/main.py），
 * 这里重复实现一遍既浪费又会和那边逻辑漂移。
 *
 * 注意：musicbrainz.org 实测直连可达（约 1s），【不需要走代理】。
 * 只有 archive.org（封面）才需要，那是另一条路径。
 */
@Service
public class MusicBrainzLookupService {

    /** MusicBrainz 要求客户端平均不超过 1 请求/秒 */
    private static final Duration MIN_INTERVAL = Duration.ofSeconds(1);

    /** 撞上 503 时再试几次、每次等多久（退避 2s、4s） */
    private static final int RATE_LIMIT_RETRIES = 2;
    private static final long RATE_LIMIT_BACKOFF_MS = 2000;

    private final HttpClient http;
    private final ObjectMapper objectMapper;
    private final ArtistMapper artistMapper;
    private final String userAgent;
    private final String baseUrl;

    private final Object throttleLock = new Object();
    private Instant lastRequestAt = Instant.EPOCH;

    public MusicBrainzLookupService(
            ObjectMapper objectMapper,
            ArtistMapper artistMapper,
            @Value("${musicbrainz.user-agent}") String userAgent,
            @Value("${musicbrainz.base-url}") String baseUrl) {
        this.objectMapper = objectMapper;
        this.artistMapper = artistMapper;
        this.userAgent = userAgent;
        this.baseUrl = baseUrl;
        this.http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
    }

    /** 简单限速。低频调用（本地搜不到时才有一次），不需要队列。 */
    private void throttle() {
        synchronized (throttleLock) {
            long waitMs = MIN_INTERVAL.toMillis() - Duration.between(lastRequestAt, Instant.now()).toMillis();
            if (waitMs > 0) {
                try {
                    Thread.sleep(waitMs);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            lastRequestAt = Instant.now();
        }
    }

    public List<MbArtistVO> searchArtists(String keyword, int limit) {
        String encoded = URLEncoder.encode(keyword, StandardCharsets.UTF_8);
        String url = baseUrl + "/artist?query=" + encoded + "&limit=" + limit + "&fmt=json";
        return parse(getJson(url), keyword);
    }

    /**
     * 发一次 GET 并解析 JSON。限速、UA、错误码、重试、JSON 解析全在这儿，两个查询共用。
     *
     * 【503 要重试，不能直接抛】限速是 1 请求/秒，我们正好卡在这个边界上，
     * 连着两条任务时很容易被 MusicBrainz 判成突发。不重试的话，
     * 一次限流 = 一条入库任务直接 FAILED（实测就是这么挂的），
     * 而用户看到的只是「抓取失败」，根本猜不到过几秒再点一次就好。
     */
    private JsonNode getJson(String url) {
        for (int attempt = 0; ; attempt++) {
            throttle();

            HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                    .header("User-Agent", userAgent)
                    .header("Accept", "application/json")
                    .timeout(Duration.ofSeconds(20))
                    .GET()
                    .build();

            HttpResponse<String> response;
            try {
                response = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            } catch (IOException e) {
                throw new ApiException(502, "连不上 MusicBrainz：" + e.getMessage());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new ApiException(502, "查询 MusicBrainz 被中断");
            }

            if (response.statusCode() == 503) {
                if (attempt >= RATE_LIMIT_RETRIES) {
                    throw new ApiException(503, "MusicBrainz 正在限流，稍后再试");
                }
                sleep((attempt + 1) * RATE_LIMIT_BACKOFF_MS);
                continue;
            }
            if (response.statusCode() == 404) {
                // 查不到不是错误，交给调用方判空
                return objectMapper.createObjectNode();
            }
            if (response.statusCode() != 200) {
                throw new ApiException(502, "MusicBrainz 返回 " + response.statusCode());
            }

            try {
                return objectMapper.readTree(response.body());
            } catch (IOException e) {
                throw new ApiException(502, "MusicBrainz 返回的不是合法 JSON");
            }
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiException(502, "查询 MusicBrainz 被中断");
        }
    }

    private List<MbArtistVO> parse(JsonNode root, String keyword) {
        List<String> needles = KeywordVariants.of(keyword);
        if (needles.isEmpty()) {
            return List.of();
        }

        // 分成两级，而不是一个 boolean。
        // 只按「名字或别名命中」筛，会让合作者的条目混进来——搜「薛之谦」时
        // 「年轮组合」因为别名里列了 `胡夏; 錘娜麗莎; 林子祥; 薛之谦` 而入选。
        // 规则：只要有人名字命中，就只给名字命中的；一个都没有才退到别名命中
        // （这样搜英文名「Jay Chou」仍然能找到名字是「周杰倫」的那个人）。
        List<MbArtistVO> byName = new ArrayList<>();
        List<MbArtistVO> byAlias = new ArrayList<>();

        for (JsonNode node : root.path("artists")) {
            MbArtistVO vo = new MbArtistVO();
            vo.setMbid(text(node, "id"));
            vo.setName(text(node, "name"));
            vo.setScore(node.path("score").asInt(0));
            vo.setCountry(text(node, "country"));
            vo.setType(text(node, "type"));
            vo.setDisambiguation(text(node, "disambiguation"));
            vo.setAliases(aliasNames(node));

            // 【必须自己按名字筛】——MusicBrainz 的 score 不能当相似度用。
            // 查「zzzzz不存在xyz」时它返回的 5 条全是 97-100 分，因为 Lucene
            // 把查询切了词、「不存在」命中了「不在」。只按分数筛等于没筛。
            if (containsAny(vo.getName(), needles)) {
                byName.add(vo);
            } else if (vo.getAliases().stream().anyMatch(a -> containsAny(a, needles))) {
                byAlias.add(vo);
            }
        }

        List<MbArtistVO> result = byName.isEmpty() ? byAlias : byName;

        // 本地库有没有这个人——前端靠这个字段决定显示「导入」还是「去他的页面」
        for (MbArtistVO vo : result) {
            if (vo.getMbid() != null) {
                vo.setLocalId(artistMapper.selectIdByMbid(vo.getMbid()));
            }
        }
        return result;
    }

    // ============================================================
    // 按需入库：找这个录音属于哪张 release
    // ============================================================

    /** 时长容差。实测同一首歌网易云与 MusicBrainz 差 0.4~1.1 秒 */
    private static final long DURATION_TOLERANCE_MS = 3000;

    /** 最多深入几个录音候选。再多也没意义——要的是它挂在哪张 release 上，不是排名 */
    private static final int MAX_RECORDING_CANDIDATES = 3;

    /**
     * 用「歌名 + 艺人（+ 时长、专辑名）」找 MusicBrainz 上的一个 release。
     *
     * 找不到返回 null —— 这是【正常结果】，不是异常：
     * 本地库对上不的歌里，本来就有相当一部分 MusicBrainz 上也没有。
     *
     * 只查这一次，不递归、不模糊猜测。挑错了会把一张不相干的专辑灌进库，
     * 比挑不到更糟——挑不到用户看得见（那首还是「未收录」），挑错了没人发现。
     */
    public MbReleaseCandidateVO findRelease(String title, String artist, Long durationMs, String albumName) {
        if (title == null || title.isBlank() || artist == null || artist.isBlank()) {
            return null;
        }

        List<String> titleNeedles = KeywordVariants.of(title);
        List<String> artistNeedles = KeywordVariants.of(artist);
        if (titleNeedles.isEmpty() || artistNeedles.isEmpty()) {
            return null;
        }

        // 先按字段查；一条都没有再退到裸关键词。
        // 字段限定太死会把「feat.」写法和标点差异全挡在门外，
        // 但反过来宽松查询的噪声也大——所以只在严格查询【空手而归】时才退
        List<JsonNode> recordings = searchRecordings(
                "recording:\"" + escape(title) + "\" AND artist:\"" + escape(artist) + "\"");
        if (recordings.isEmpty()) {
            recordings = searchRecordings(escape(title) + " " + escape(artist));
        }

        List<JsonNode> candidates = rank(recordings, titleNeedles, artistNeedles, durationMs);

        for (JsonNode candidate : candidates.subList(0, Math.min(MAX_RECORDING_CANDIDATES, candidates.size()))) {
            MbReleaseCandidateVO picked = pickRelease(candidate, albumName);
            if (picked != null) {
                return picked;
            }
        }
        return null;
    }

    private List<JsonNode> searchRecordings(String query) {
        String url = baseUrl + "/recording?query="
                + URLEncoder.encode(query, StandardCharsets.UTF_8)
                + "&limit=10&fmt=json";

        List<JsonNode> list = new ArrayList<>();
        getJson(url).path("recordings").forEach(list::add);
        return list;
    }

    /**
     * 按名字筛 + 按时长分档排序。
     *
     * 【必须自己筛】——和 searchArtists 里那段同理，MusicBrainz 的 score 不是相似度：
     * 实测搜「我不难过」时简繁两版都返回 100 分，搜不存在的词也照样 97 分起。
     *
     * 分档而不是硬过滤：时长对得上的排最前，拿不到时长的排中间，对不上的垫底兜住。
     * 不能把「对不上」直接丢掉——电台版/重制版本来就差得多，而且本地 track 表
     * 有 265 行 duration_ms 是 NULL，一刀切会让这些歌永远入不了库。
     */
    private static List<JsonNode> rank(List<JsonNode> recordings,
                                       List<String> titleNeedles,
                                       List<String> artistNeedles,
                                       Long durationMs) {
        List<JsonNode> hit = new ArrayList<>();
        List<JsonNode> unknown = new ArrayList<>();
        List<JsonNode> mismatch = new ArrayList<>();

        for (JsonNode node : recordings) {
            if (!containsAnyNoSpace(text(node, "title"), titleNeedles)) {
                continue;
            }
            if (!artistCreditContains(node, artistNeedles)) {
                continue;
            }
            switch (durationTier(node, durationMs)) {
                case 0 -> hit.add(node);
                case 1 -> unknown.add(node);
                default -> mismatch.add(node);
            }
        }

        List<JsonNode> ordered = new ArrayList<>(hit);
        ordered.addAll(unknown);
        ordered.addAll(mismatch);
        return ordered;
    }

    /** 0 = 对得上，1 = 拿不到时长（两边任一为空都算），2 = 对不上 */
    private static int durationTier(JsonNode recording, Long durationMs) {
        if (durationMs == null || durationMs <= 0) {
            return 1;
        }
        JsonNode length = recording.get("length");
        if (length == null || length.isNull() || length.asLong() <= 0) {
            return 1;
        }
        return Math.abs(length.asLong() - durationMs) <= DURATION_TOLERANCE_MS ? 0 : 2;
    }

    private static boolean artistCreditContains(JsonNode recording, List<String> needles) {
        for (JsonNode credit : recording.path("artist-credit")) {
            if (containsAnyNoSpace(text(credit, "name"), needles)
                    || containsAnyNoSpace(text(credit.path("artist"), "name"), needles)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 从搜索结果的这一条 recording 里挑一张 release。
     *
     * 【releases 直接来自搜索结果，不再单独发请求】
     * recording 的搜索响应里每条本来就带着 releases（含 status / date /
     * release-group.primary-type），原先还去 /recording/{id}?inc=releases
     * 问一遍是白花的——限速 1 请求/秒，一次就是 1 秒，每首歌都要多等这么久。
     * 实测确认过：搜「我不难过」返回的两条，releases 一个 6 张一个 1 张，字段齐全。
     *
     * 挑法按重要性从高到低：专辑名对得上 → Official → Album/EP/Single → 最早 → id 升序。
     * 最后两项是为了【确定性】：条件全平时也得每次挑到同一张，
     * 否则同一首歌重试两次会灌进两张不同的专辑。
     */
    private MbReleaseCandidateVO pickRelease(JsonNode recording, String albumName) {
        Comparator<JsonNode> order = releaseOrder(albumName);

        JsonNode best = null;
        for (JsonNode release : recording.path("releases")) {
            if (text(release, "id") == null) {
                continue;
            }
            if (best == null || order.compare(release, best) < 0) {
                best = release;
            }
        }
        if (best == null) {
            return null;
        }

        MbReleaseCandidateVO vo = new MbReleaseCandidateVO();
        vo.setMbid(text(best, "id"));
        vo.setTitle(text(best, "title"));
        vo.setDate(text(best, "date"));
        vo.setStatus(text(best, "status"));
        // 艺人取 recording 的。搜索结果里的 release 节点不一定带 artist-credit，
        // 但 recording 一定有，而且它才是我们筛过的那个
        vo.setArtist(firstCreditName(recording));
        JsonNode group = best.path("release-group");
        vo.setPrimaryType(text(group, "primary-type"));
        vo.setReleaseGroupTitle(text(group, "title"));
        return vo;
    }

    /** 挑 release 的总序。比小者胜 */
    private static Comparator<JsonNode> releaseOrder(String albumName) {
        List<String> needles = KeywordVariants.of(albumName == null ? "" : albumName);
        return Comparator
                .comparingInt((JsonNode r) -> albumRank(r, needles))
                .thenComparingInt(r -> "Official".equals(text(r, "status")) ? 0 : 1)
                .thenComparingInt(r -> typeRank(text(r.path("release-group"), "primary-type")))
                .thenComparing(r -> text(r, "date"), Comparator.nullsLast(Comparator.naturalOrder()))
                .thenComparing(r -> text(r, "id"), Comparator.nullsLast(Comparator.naturalOrder()));
    }

    private static int albumRank(JsonNode release, List<String> needles) {
        if (needles == null || needles.isEmpty()) {
            return 0;
        }
        JsonNode group = release.path("release-group");
        boolean hit = containsAnyNoSpace(text(release, "title"), needles)
                || containsAnyNoSpace(text(group, "title"), needles);
        return hit ? 0 : 1;
    }

    private static int typeRank(String primaryType) {
        if (primaryType == null) {
            return 3;
        }
        return switch (primaryType) {
            case "Album" -> 0;
            case "EP" -> 1;
            case "Single" -> 2;
            default -> 3;
        };
    }

    private static String firstCreditName(JsonNode node) {
        for (JsonNode credit : node.path("artist-credit")) {
            String name = text(credit, "name");
            if (name != null) {
                return name;
            }
        }
        return null;
    }

    /** Lucene 查询串里的引号和反斜杠要转义，否则歌名带引号会把查询拆坏 */
    private static String escape(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    /**
     * 文本是否包含任一（繁简）变体，【忽略空格】，大小写不敏感。
     *
     * 和 containsAny 的区别：那边只对 needles 去空格（KeywordVariants.of 已经去过了），
     * 文本一侧原样比。搜索页显示用那个就够了，但这里比的是 MusicBrainz 的名字，
     * 空格差异正是要吃掉的东西——「G.E.M.邓紫棋」对「G.E.M. 鄧紫棋」。
     */
    private static boolean containsAnyNoSpace(String text, List<String> needles) {
        if (text == null) {
            return false;
        }
        String squeezed = text.toLowerCase().replace(" ", "");
        return needles.stream().anyMatch(n -> squeezed.contains(n.toLowerCase()));
    }

    /** 文本是否包含任一（繁简）变体。大小写不敏感。 */
    private static boolean containsAny(String text, List<String> needles) {
        if (text == null) {
            return false;
        }
        String lower = text.toLowerCase();
        return needles.stream().anyMatch(n -> lower.contains(n.toLowerCase()));
    }

    private static List<String> aliasNames(JsonNode node) {
        List<String> names = new ArrayList<>();
        for (JsonNode alias : node.path("aliases")) {
            String name = text(alias, "name");
            if (name != null && !names.contains(name)) {
                names.add(name);
            }
        }
        return names;
    }

    private static String text(JsonNode node, String field) {
        JsonNode v = node.get(field);
        return (v == null || v.isNull()) ? null : v.asText();
    }
}
