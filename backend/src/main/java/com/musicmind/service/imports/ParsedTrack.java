package com.musicmind.service.imports;

import lombok.Data;

import java.util.List;

/**
 * 从外部歌单抓到的一首，平台无关。
 *
 * artists 是【列表】而不是拼好的字符串：外部歌单一首歌常有多个艺人
 * （「周杰伦 / 阿信」），但匹配时只该用【主艺人】，拿整串去比会误命中。
 * 展示用的拼接字符串在 ImportItemVO 里现拼。
 *
 * durationMs 是【毫秒】——两个平台的原始单位不一样（网易云是毫秒、
 * QQ音乐是秒），换算在各自的 Provider 里做完，到这里统一成毫秒。
 */
@Data
public class ParsedTrack {
    /**
     * 平台上这首歌的 id（网易云是数字 id，QQ 音乐是 songmid 字符串）。
     * 统一成 String，落库去重用。
     *
     * 【为什么不复用 durationMs + title 去重】同一首歌在歌单里可以合法地
     * 出现两次，用平台 id 才是唯一且诚实的标识。
     */
    private String externalId;

    /** 主艺人在前 */
    private List<String> artists = List.of();
    private String title;
    private String albumName;

    /**
     * 平台的专辑 id（v3 的 al.id）。**只在抓取过程中用**（批量查发行年时按它去重），
     * 不落库。
     */
    private Long albumId;

    /**
     * 发行年（网易云：专辑详情接口的 album.publishTime）。
     * 【为什么值得多花一串请求】未入库的歌是画像的黑洞 —— 这半边占了近一半，
     * 补齐发行年后「年代」维度至少能不偏。QQ 的平台字段里没有可靠来源，留 null。
     */
    private Integer releaseYear;

    private Long durationMs;

    /**
     * 平台给的封面 URL（原样存，不带缩放参数）。
     * 【对齐前就靠它显示封面】——这是「导入即完整可见」的关键：
     * 没进本地库的歌也有图，不用等 MusicBrainz。
     */
    private String coverUrl;

    /** 主艺人，匹配时用这个 */
    public String primaryArtist() {
        return artists.isEmpty() ? null : artists.get(0);
    }

    /** 展示用：全部艺人拼起来 */
    public String artistsText() {
        return String.join(" / ", artists);
    }
}
