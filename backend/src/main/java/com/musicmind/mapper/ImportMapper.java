package com.musicmind.mapper;

import com.musicmind.vo.RematchCandidateVO;
import com.musicmind.vo.TrackMatchVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ImportMapper {

    /**
     * 在本地库里找一首：歌名【精确】匹配 + 主艺人匹配。
     *
     * t1..t3 / a1..a3 各是歌名和艺人的繁简变体（KeywordVariants 生成，
     * 不足三个时用第一个填满，所以永远非空）。
     *
     * 【只做精确匹配】——更进一步的规范化（去括号、去 feat.、时长校验）
     * 留给下一步的实体对齐。时长这次已经抓到了，是那一步的弹药。
     *
     * 【但空格要归一】两边都套一层 REPLACE(x, ' ', '')。网易云写
     * 「G.E.M.邓紫棋」，MusicBrainz 写「G.E.M. 鄧紫棋」，就差一个空格——
     * 这跟繁简一样是同一个名字的两种写法，不是需要语义理解的模糊匹配，
     * 不该等到「对齐」那一步。修之前它一个字母不差地把 20 首全挡在门外。
     *
     * 【时长用来排序，不用来过滤】dur 传外部时长（毫秒，可能为 NULL）。
     * 同名同艺人的录音常常有好几个版本（专辑版/现场版/重制版），
     * 时长是唯一能廉价拿到的区分信号——所以在多个候选里挑距离最近的那个。
     *
     * 为什么不直接 `ABS(...) < 3000` 硬过滤：实测会误伤。
     * 歌单里《出现又离开 (Live)》404 秒，MusicBrainz 同一首现场版 416 秒，
     * 差 12.6 秒——明明是同一首歌，硬过滤却判成「不同版本」，
     * 那一行就永远对不上、永远收藏不了。宁可挑一个略长的版本，
     * 也不要让用户看着一首明明在库里的歌点不动收藏。
     *
     * 【CAST 成 SIGNED 是必须的】track.duration_ms 是 BIGINT UNSIGNED，
     * 直接相减，只要本地时长小于外部时长就出负数，MySQL 不是返回负数而是
     * 报 "BIGINT UNSIGNED value is out of range" —— 整条 SQL 失败、整个导入 500。
     * 实测就是这么炸的，两百首歌全被这一条挡在门外。
     *
     * 三个「比不了」的口子：本地时长缺失（track 表有 265 行是 NULL）、
     * 外部时长缺失（平台没给）、dur <= 0（脏数据）。这些行排到最后但不排除。
     *
     * 匹配不上返回 null，交给上层原样报告给用户，不要硬凑。
     */
    @Select("""
            SELECT t.id   AS track_id,
                   t.name AS track_name,
                   alb.id   AS album_id,
                   alb.name AS album_name
            FROM track t
            LEFT JOIN album alb ON alb.id = (
                    SELECT mr2.album_id
                    FROM release_track rt2
                    JOIN music_release mr2 ON mr2.id = rt2.release_id
                    WHERE rt2.track_id = t.id
                    ORDER BY mr2.release_date IS NULL, mr2.release_date, mr2.id
                    LIMIT 1)
            WHERE (REPLACE(t.name, ' ', '') IN (REPLACE(#{t1}, ' ', ''), REPLACE(#{t2}, ' ', ''), REPLACE(#{t3}, ' ', ''))
                -- 库名常带英文副题（「流行歌曲 (Popular Songs)」），剥掉括号后缀再比一次。
                -- 和 KeywordVariants.of 的剥括号变体【对称】—— 两边都做，只做一边没用
                OR REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(t.name, '(', 1), '（', 1), ' ', '')
                   IN (REPLACE(#{t1}, ' ', ''), REPLACE(#{t2}, ' ', ''), REPLACE(#{t3}, ' ', '')))
              AND EXISTS (
                    SELECT 1 FROM track_artist ta
                    JOIN artist ar ON ar.id = ta.artist_id
                    WHERE ta.track_id = t.id
                      AND (REPLACE(ar.name, ' ', '') IN (REPLACE(#{a1}, ' ', ''), REPLACE(#{a2}, ' ', ''), REPLACE(#{a3}, ' ', ''))
                        OR REPLACE(ta.credited_name, ' ', '') IN (REPLACE(#{a1}, ' ', ''), REPLACE(#{a2}, ' ', ''), REPLACE(#{a3}, ' ', '')))
                  )
            ORDER BY
              -- ① 能比大小的排前面。任何一边没有时长就没法比，垫底
              (t.duration_ms IS NULL OR #{dur} IS NULL OR #{dur} <= 0),
              -- ② 时长距离最近的优先
              ABS(CAST(t.duration_ms AS SIGNED) - CAST(#{dur} AS SIGNED)),
              -- ③ 全平时用 id 定序，保证同一首歌每次挑到同一行
              t.id
            LIMIT 1
            """)
    TrackMatchVO matchTrack(@Param("t1") String t1,
                            @Param("t2") String t2,
                            @Param("t3") String t3,
                            @Param("a1") String a1,
                            @Param("a2") String a2,
                            @Param("a3") String a3,
                            @Param("dur") Long dur);

    /**
     * 按本地 track id 取展示信息。
     *
     * 用于「对齐只前进不倒退」：重新导入时新匹配失败、但上次对上了，
     * 要照着旧结果显示，就得把旧 track 的名字和专辑捞回来。
     */
    @Select("""
            SELECT t.id   AS track_id,
                   t.name AS track_name,
                   alb.id   AS album_id,
                   alb.name AS album_name
            FROM track t
            LEFT JOIN album alb ON alb.id = (
                    SELECT mr2.album_id
                    FROM release_track rt2
                    JOIN music_release mr2 ON mr2.id = rt2.release_id
                    WHERE rt2.track_id = t.id
                    ORDER BY mr2.release_date IS NULL, mr2.release_date, mr2.id
                    LIMIT 1)
            WHERE t.id = #{trackId}
            """)
    TrackMatchVO selectTrackById(@Param("trackId") Long trackId);

    /**
     * 入库之后回头捞人：本地库里【还没对齐】的行里，艺人像这个人的。
     *
     * 【跨用户跨歌单全表扫】——按需入库的产物是全库共享的，
     * 甲导入的歌单会因为乙点的「入库」而变得可收藏，这是特性不是 bug。
     * 表就几万行、idx_upt_user_status 顶着，当前量级不做优化。
     *
     * LIKE 只用来【粗筛】，命中的行还会逐行走一遍完整的 matchTrack，
     * 所以手艺人名里万一有 % 或 _ 导致多召回几行，也只是多跑几条 SQL，不会误判。
     * 用 LIKE 而不是 IN：artists 存的是「周杰伦 / 温岚」这种拼接串，
     * 主艺人之外的位置也得能命中，否则合唱曲目永远捞不出来。
     */
    @Select("""
            SELECT id AS row_id,
                   import_id,
                   external_id,
                   title,
                   artists,
                   duration_ms
            FROM user_playlist_track
            WHERE user_removed = 0
              AND match_status <> 'MATCHED'
              AND (REPLACE(artists, ' ', '') LIKE CONCAT('%', REPLACE(#{a1}, ' ', ''), '%')
                OR REPLACE(artists, ' ', '') LIKE CONCAT('%', REPLACE(#{a2}, ' ', ''), '%')
                OR REPLACE(artists, ' ', '') LIKE CONCAT('%', REPLACE(#{a3}, ' ', ''), '%'))
            """)
    List<RematchCandidateVO> selectRematchCandidates(@Param("a1") String a1,
                                                     @Param("a2") String a2,
                                                     @Param("a3") String a3);
}
