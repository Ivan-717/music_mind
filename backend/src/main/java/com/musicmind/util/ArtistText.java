package com.musicmind.util;

/**
 * user_playlist_track.artists 那一列的解析。
 *
 * 列里存的是外部原样的拼接串（ParsedTrack.artistsText() 用 " / " 连起来），
 * 形如「周杰伦 / 温岚」。对齐时只能拿【主艺人】去比——整串去比会误命中，
 * 而且 matchTrack 那边比的是 track_artist 里的单个艺人名。
 */
public final class ArtistText {

    private ArtistText() {
    }

    /**
     * 主艺人。空串 / 空返回 null。
     *
     * 【按 " / " 切，不能按裸 '/' 切】拼接用的是 " / "（前后都有空格），
     * 而单个艺人名里是可以有斜杠的：歌单里存「AC/DC」时，按裸 '/' 切会得到
     * 「AC」——拿它去比 artist.name 永远对不上，去 MusicBrainz 搜也搜的是别人，
     * 这首歌会永久停在「未收录」而且点入库也没用。
     * 单个艺人名里不会出现 " / "（有空格），所以按它切是安全的。
     */
    public static String primary(String artists) {
        if (artists == null) {
            return null;
        }
        String trimmed = artists.trim();
        if (trimmed.isEmpty()) {
            return null;
        }
        int sep = trimmed.indexOf(" / ");
        String first = (sep < 0 ? trimmed : trimmed.substring(0, sep)).trim();

        // 再去掉首尾残留的 '/'。
        // 【为什么需要】先 trim 会吃掉两侧空格，于是 " / "（歌手字段是空的脏数据）
        // 变成 "/"，这时已经找不到 " / " 分隔符了，不挡的话会返回一个叫「/」的艺人——
        // 拿它去搜 MusicBrainz 和比 artist.name 都是纯浪费。
        // 只削首尾，不动中间的，所以 AC/DC 不受影响
        int start = 0;
        int end = first.length();
        while (start < end && first.charAt(start) == '/') {
            start++;
        }
        while (end > start && first.charAt(end - 1) == '/') {
            end--;
        }
        String name = first.substring(start, end).trim();
        return name.isEmpty() ? null : name;
    }
}
