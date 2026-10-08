package com.musicmind.mapper;

import com.musicmind.vo.AlbumSearchVO;
import com.musicmind.vo.ArtistSearchVO;
import com.musicmind.vo.TrackSearchVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface SearchMapper {

    /**
     * 曲目搜索。
     *
     * 匹配范围两块：歌名本身，以及【这首歌的艺人名】。
     * 后者是为了「搜歌手名能找到他的歌」——搜「周杰伦」时歌名含这三个字的
     * 只有 2 首，而他唱的曲目有 780 首。
     *
     * 排序 rank_no（顺序是踩过坑调的，别乱改）：
     *   0 = 歌名精确
     *   1 = 歌名前缀
     *   2 = 靠艺人名匹配上的     ← 排在「歌名包含」【之前】
     *   3 = 歌名包含
     *
     * 为什么 2 要排在 3 前面：搜「周杰伦」时，歌名碰巧含这三个字的
     * （「周杰倫的大兵秘辛日記」这类幕后花絮）会压在真正属于他的歌前面——
     * 那恰好是用户想要的结果的反面。
     *
     * 去重：只对 rank 2 那一档按歌名去重。MusicBrainz 会给同一首歌在不同
     * 精选集里分配不同 recording MBID（全库 1898 条曲目只有 1379 个不同名字）。
     * 歌名匹配档【不去重】——搜「晴天」时用户可能想看 live 版。
     */
    @Select("""
            SELECT picked.id AS track_id, picked.name, tk.duration_ms,
                   alb.id   AS album_id,
                   alb.name AS album_name,
                   GROUP_CONCAT(
                       CONCAT(COALESCE(ta.credited_name, ar.name),
                              COALESCE(ta.join_phrase, ''))
                       ORDER BY ta.id SEPARATOR ''
                   ) AS artist_names,
                   EXISTS(SELECT 1 FROM track_audio_feature f
                          WHERE f.track_id = picked.id
                            AND f.preview_url IS NOT NULL
                            AND f.preview_url <> '') AS has_preview
            FROM (
                SELECT MIN(y.id)         AS id,
                       MIN(y.name)       AS name,
                       MIN(y.first_date) AS first_date,
                       MIN(y.rank_no)    AS rank_no
                FROM (
                    SELECT tk0.id, tk0.name, rel.first_date,
                           CASE WHEN REPLACE(tk0.name, ' ', '') IN (#{v1}, #{v2}, #{v3}) THEN 0
                                WHEN REPLACE(tk0.name, ' ', '') LIKE CONCAT(#{v1}, '%')
                                  OR REPLACE(tk0.name, ' ', '') LIKE CONCAT(#{v2}, '%')
                                  OR REPLACE(tk0.name, ' ', '') LIKE CONCAT(#{v3}, '%') THEN 1
                                WHEN EXISTS (
                                     SELECT 1 FROM track_artist ta0
                                     JOIN artist ar0 ON ar0.id = ta0.artist_id
                                     WHERE ta0.track_id = tk0.id
                                       AND (REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                                         OR REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                                         OR REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
                                         OR REPLACE(ta0.credited_name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                                         OR REPLACE(ta0.credited_name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                                         OR REPLACE(ta0.credited_name, ' ', '') LIKE CONCAT('%', #{v3}, '%'))
                                   ) THEN 2
                                ELSE 3 END
                           -- 超长曲目降一档。MusicBrainz 把幕后花絮、影音特辑、
                           -- 演唱会串烧也建模成 recording，它们动辄 15-27 分钟。
                           -- 全库 1898 条里 >10 分钟的只有 22 条（1.2%），所以这个
                           -- 阈值几乎不会误伤正常歌曲，却能把「周杰倫的大兵秘辛日記」
                           -- 这类东西从搜索结果头部挪走。
                           + CASE WHEN tk0.duration_ms > 600000 THEN 4 ELSE 0 END AS rank_no
                    FROM track tk0
                    LEFT JOIN (
                        SELECT rt2.track_id, MIN(a2.release_date) AS first_date
                        FROM release_track rt2
                        JOIN music_release mr2 ON mr2.id = rt2.release_id
                        JOIN album a2          ON a2.id = mr2.album_id
                        GROUP BY rt2.track_id
                    ) rel ON rel.track_id = tk0.id
                    WHERE REPLACE(tk0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                       OR REPLACE(tk0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                       OR REPLACE(tk0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
                       OR EXISTS (
                            SELECT 1 FROM track_artist ta1
                            JOIN artist ar1 ON ar1.id = ta1.artist_id
                            WHERE ta1.track_id = tk0.id
                              AND (REPLACE(ar1.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                                OR REPLACE(ar1.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                                OR REPLACE(ar1.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
                                OR REPLACE(ta1.credited_name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                                OR REPLACE(ta1.credited_name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                                OR REPLACE(ta1.credited_name, ' ', '') LIKE CONCAT('%', #{v3}, '%'))
                          )
                ) y
                GROUP BY CASE WHEN y.rank_no = 2 THEN y.name ELSE CONCAT('id:', y.id) END
            ) picked
            JOIN track tk ON tk.id = picked.id
            LEFT JOIN album alb ON alb.id = (
                    SELECT mr2.album_id
                    FROM release_track rt2
                    JOIN music_release mr2 ON mr2.id = rt2.release_id
                    WHERE rt2.track_id = tk.id
                    ORDER BY mr2.release_date IS NULL, mr2.release_date, mr2.id
                    LIMIT 1)
            LEFT JOIN track_artist ta ON ta.track_id = tk.id
            LEFT JOIN artist ar       ON ar.id = ta.artist_id
            GROUP BY picked.id, picked.rank_no, picked.name, picked.first_date,
                     tk.duration_ms, alb.id, alb.name
            ORDER BY picked.rank_no,
                     CASE WHEN picked.rank_no < 2 THEN CHAR_LENGTH(picked.name) ELSE 0 END,
                     picked.first_date IS NULL, picked.first_date, picked.name, picked.id
            LIMIT #{limit}
            """)
    List<TrackSearchVO> searchTracks(@Param("v1") String v1,
                                     @Param("v2") String v2,
                                     @Param("v3") String v3,
                                     @Param("limit") int limit);

    @Select("""
            SELECT picked.id, picked.name, a.release_date,
                   GROUP_CONCAT(
                       CONCAT(COALESCE(aa.credited_name, ar.name),
                              COALESCE(aa.join_phrase, ''))
                       ORDER BY aa.id SEPARATOR ''
                   ) AS artist_names
            FROM (
                SELECT a0.id, a0.name,
                       CASE WHEN REPLACE(a0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                              OR REPLACE(a0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                              OR REPLACE(a0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
                            THEN CASE WHEN REPLACE(a0.name, ' ', '') IN (#{v1}, #{v2}, #{v3}) THEN 0
                                      WHEN REPLACE(a0.name, ' ', '') LIKE CONCAT(#{v1}, '%')
                                        OR REPLACE(a0.name, ' ', '') LIKE CONCAT(#{v2}, '%')
                                        OR REPLACE(a0.name, ' ', '') LIKE CONCAT(#{v3}, '%') THEN 1
                                      ELSE 2 END
                            ELSE 3 END AS rank_no
                FROM album a0
                WHERE REPLACE(a0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                   OR REPLACE(a0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                   OR REPLACE(a0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
                   OR EXISTS (
                        SELECT 1 FROM album_artist aa0
                        JOIN artist ar1 ON ar1.id = aa0.artist_id
                        WHERE aa0.album_id = a0.id
                          AND (REPLACE(ar1.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                            OR REPLACE(ar1.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                            OR REPLACE(ar1.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
                            OR REPLACE(aa0.credited_name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                            OR REPLACE(aa0.credited_name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                            OR REPLACE(aa0.credited_name, ' ', '') LIKE CONCAT('%', #{v3}, '%'))
                      )
                ORDER BY rank_no, CHAR_LENGTH(a0.name), a0.name
                LIMIT #{limit}
            ) picked
            JOIN album a ON a.id = picked.id
            LEFT JOIN album_artist aa ON aa.album_id = a.id
            LEFT JOIN artist ar       ON ar.id = aa.artist_id
            GROUP BY picked.id, picked.rank_no, picked.name, a.release_date
            ORDER BY picked.rank_no, CHAR_LENGTH(picked.name), picked.name
            """)
    List<AlbumSearchVO> searchAlbums(@Param("v1") String v1,
                                     @Param("v2") String v2,
                                     @Param("v3") String v3,
                                     @Param("limit") int limit);

    /**
     * 歌手额外搜 artist_alias（库里有 321 行，含英文名），
     * 这样搜「Jay Chou」能找到「周杰倫」。
     * 用 EXISTS 而不是 JOIN，因为歌手名是单值，不需要 GROUP_CONCAT，
     * 也就避开了「GROUP BY 打乱顺序」那个坑。
     */
    @Select("""
            SELECT picked.id, picked.name, a.disambiguation
            FROM (
                SELECT ar0.id, ar0.name,
                       CASE WHEN REPLACE(ar0.name, ' ', '') IN (#{v1}, #{v2}, #{v3}) THEN 0
                            WHEN EXISTS (SELECT 1 FROM artist_alias al0
                                         WHERE al0.artist_id = ar0.id
                                           AND REPLACE(al0.name, ' ', '') IN (#{v1}, #{v2}, #{v3})) THEN 1
                            WHEN REPLACE(ar0.name, ' ', '') LIKE CONCAT(#{v1}, '%')
                              OR REPLACE(ar0.name, ' ', '') LIKE CONCAT(#{v2}, '%')
                              OR REPLACE(ar0.name, ' ', '') LIKE CONCAT(#{v3}, '%') THEN 2
                            WHEN EXISTS (SELECT 1 FROM artist_alias al1
                                         WHERE al1.artist_id = ar0.id
                                           AND (REPLACE(al1.name, ' ', '') LIKE CONCAT(#{v1}, '%')
                                             OR REPLACE(al1.name, ' ', '') LIKE CONCAT(#{v2}, '%')
                                             OR REPLACE(al1.name, ' ', '') LIKE CONCAT(#{v3}, '%'))) THEN 3
                            ELSE 4 END AS rank_no
                FROM artist ar0
                WHERE REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                   OR REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                   OR REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
                   OR EXISTS (SELECT 1 FROM artist_alias al2
                              WHERE al2.artist_id = ar0.id
                                AND (REPLACE(al2.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                                  OR REPLACE(al2.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                                  OR REPLACE(al2.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')))
                ORDER BY rank_no, CHAR_LENGTH(ar0.name), ar0.name
                LIMIT #{limit}
            ) picked
            JOIN artist a ON a.id = picked.id
            ORDER BY picked.rank_no, CHAR_LENGTH(picked.name), picked.name
            """)
    List<ArtistSearchVO> searchArtists(@Param("v1") String v1,
                                       @Param("v2") String v2,
                                       @Param("v3") String v3,
                                       @Param("limit") int limit);

    // ============================================================
    // 总数查询
    //
    // ⚠️ 匹配条件必须和上面三个 search 方法【逐字一致】，否则会出现
    //    「显示 10 / 780，但实际只有 12 条」这种对不上的情况。
    //    改匹配条件时，这 6 个方法一起改（3 个 search + 3 个 count）。
    // ============================================================

    /**
     * 曲目总数。口径必须和 searchTracks 的去重规则一致：
     *   歌名匹配的  → 全部计数（不去重）
     *   艺人名匹配的 → 按歌名去重计数
     * 不一致的话前端会出现「显示 50 / 363，但翻到底只有 80 条」这种对不上。
     */
    @Select("""
            SELECT
              (SELECT COUNT(*) FROM track tk0
               WHERE REPLACE(tk0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                  OR REPLACE(tk0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                  OR REPLACE(tk0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%'))
            + (SELECT COUNT(DISTINCT tk0.name) FROM track tk0
               WHERE NOT (REPLACE(tk0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                       OR REPLACE(tk0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                       OR REPLACE(tk0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%'))
                 AND EXISTS (
                      SELECT 1 FROM track_artist ta0
                      JOIN artist ar0 ON ar0.id = ta0.artist_id
                      WHERE ta0.track_id = tk0.id
                        AND (REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                          OR REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                          OR REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
                          OR REPLACE(ta0.credited_name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                          OR REPLACE(ta0.credited_name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                          OR REPLACE(ta0.credited_name, ' ', '') LIKE CONCAT('%', #{v3}, '%'))
                    ))
            """)
    int countTracks(@Param("v1") String v1,
                    @Param("v2") String v2,
                    @Param("v3") String v3);

    @Select("""
            SELECT COUNT(*)
            FROM album a0
            WHERE REPLACE(a0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
               OR REPLACE(a0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
               OR REPLACE(a0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
               OR EXISTS (
                    SELECT 1 FROM album_artist aa0
                    JOIN artist ar1 ON ar1.id = aa0.artist_id
                    WHERE aa0.album_id = a0.id
                      AND (REPLACE(ar1.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                        OR REPLACE(ar1.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                        OR REPLACE(ar1.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
                        OR REPLACE(aa0.credited_name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                        OR REPLACE(aa0.credited_name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                        OR REPLACE(aa0.credited_name, ' ', '') LIKE CONCAT('%', #{v3}, '%'))
                  )
            """)
    int countAlbums(@Param("v1") String v1,
                    @Param("v2") String v2,
                    @Param("v3") String v3);

    @Select("""
            SELECT COUNT(*)
            FROM artist ar0
            WHERE REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
               OR REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
               OR REPLACE(ar0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%')
               OR EXISTS (
                    SELECT 1 FROM artist_alias al0
                    WHERE al0.artist_id = ar0.id
                      AND (REPLACE(al0.name, ' ', '') LIKE CONCAT('%', #{v1}, '%')
                        OR REPLACE(al0.name, ' ', '') LIKE CONCAT('%', #{v2}, '%')
                        OR REPLACE(al0.name, ' ', '') LIKE CONCAT('%', #{v3}, '%'))
                  )
            """)
    int countArtists(@Param("v1") String v1,
                     @Param("v2") String v2,
                     @Param("v3") String v3);
}
