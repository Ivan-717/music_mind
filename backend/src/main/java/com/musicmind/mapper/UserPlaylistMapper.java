package com.musicmind.mapper;

import com.musicmind.entity.UserPlaylistImport;
import com.musicmind.entity.UserPlaylistTrack;
import com.musicmind.vo.ImportedTrackVO;
import org.apache.ibatis.annotations.*;

import java.util.List;

/**
 * 导入歌单（用户侧数据）的读写。
 *
 * 和 ImportMapper 的分工：
 *   ImportMapper        —— 拿外部的一首歌去【本地 MusicBrainz 库】里找对应曲目（对齐用，只读事实表）
 *   UserPlaylistMapper  —— 存/取【用户导入的外部原始数据】本身
 */
@Mapper
public interface UserPlaylistMapper {

    /** 找这个用户这个歌单已有的导入记录（重复导入时复用，靠唯一键） */
    @Select("""
            SELECT id, user_id, provider, external_playlist_id, playlist_name,
                   source_url, track_count, last_imported_at
            FROM user_playlist_import
            WHERE user_id = #{userId} AND provider = #{provider}
              AND external_playlist_id = #{externalPlaylistId}
            """)
    UserPlaylistImport findImport(@Param("userId") Long userId,
                                  @Param("provider") String provider,
                                  @Param("externalPlaylistId") String externalPlaylistId);

    /** 按 id 取，同时校验归属——查别人的歌单要查不到，不能只靠前端不点 */
    @Select("""
            SELECT id, user_id, provider, external_playlist_id, playlist_name,
                   source_url, track_count, last_imported_at
            FROM user_playlist_import
            WHERE id = #{id} AND user_id = #{userId}
            """)
    UserPlaylistImport findOwnedImport(@Param("id") Long id, @Param("userId") Long userId);

    @Insert("""
            INSERT INTO user_playlist_import
                (user_id, provider, external_playlist_id, playlist_name, source_url,
                 track_count, last_imported_at)
            VALUES
                (#{userId}, #{provider}, #{externalPlaylistId}, #{playlistName}, #{sourceUrl},
                 #{trackCount}, NOW())
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insertImport(UserPlaylistImport row);

    @Update("""
            UPDATE user_playlist_import
               SET playlist_name = #{playlistName}, source_url = #{sourceUrl},
                   track_count = #{trackCount}, last_imported_at = NOW()
             WHERE id = #{id}
            """)
    int updateImport(UserPlaylistImport row);

    /**
     * 插或更新一首歌。
     *
     * 【关键】ON DUPLICATE KEY UPDATE 里【不碰】match_status / matched_track_id——
     * 那两列是对齐的结果，重复导入不该把它清掉，否则对齐要白跑一遍。
     */
    @Insert("""
            INSERT INTO user_playlist_track
                (import_id, user_id, provider, external_id, position,
                 title, artists, album_name, duration_ms, cover_url)
            VALUES
                (#{importId}, #{userId}, #{provider}, #{externalId}, #{position},
                 #{title}, #{artists}, #{albumName}, #{durationMs}, #{coverUrl})
            ON DUPLICATE KEY UPDATE
                position = VALUES(position),
                title = VALUES(title),
                artists = VALUES(artists),
                album_name = VALUES(album_name),
                duration_ms = VALUES(duration_ms),
                cover_url = VALUES(cover_url)
            """)
    int upsertTrack(UserPlaylistTrack row);

    /**
     * 按 (import_id, external_id) 找回一行。
     *
     * 【为什么要它】upsertTrack 是 INSERT ... ON DUPLICATE KEY UPDATE，
     * 命中已存在的行时拿不到自增 id（lastInsertId 不可靠）。
     * 而排入库任务要 track_row_id —— 只能回头查一次。
     */
    @Select("""
            SELECT id, import_id, user_id, provider, external_id, position,
                   title, artists, album_name, duration_ms, cover_url,
                   match_status, matched_track_id
            FROM user_playlist_track
            WHERE import_id = #{importId} AND external_id = #{externalId}
            """)
    UserPlaylistTrack findTrackRowByExternalId(@Param("importId") Long importId,
                                               @Param("externalId") String externalId);

    /**
     * 把一首歌的对齐结果写回库。
     *
     * 【这是「我的歌单」页能不能收藏的前提】——不写回的话 match_status 永远是
     * PENDING、matched_track_id 永远是 NULL，页面上所有 ♡ 都是禁用的，
     * 「全部加入收藏」会一首也收藏不上。
     *
     * upsertTrack 的 ON DUPLICATE KEY UPDATE 里【故意不碰】这两列（避免重复导入
     * 覆盖已有结果），所以对齐结果必须由这个独立方法显式写。
     *
     * 定位用 (import_id, external_id)，正好走 uk_upt_import_external 唯一键，很快。
     */
    @Update("""
            UPDATE user_playlist_track
               SET match_status = #{status},
                   matched_track_id = #{trackId},
                   matched_at = NOW()
             WHERE import_id = #{importId} AND external_id = #{externalId}
            """)
    int updateMatch(@Param("importId") Long importId,
                    @Param("externalId") String externalId,
                    @Param("status") String status,
                    @Param("trackId") Long trackId);

    /**
     * 这次导入没出现、但库里还留着的曲目（歌单里被删了）——删掉。
     *
     * keepExternalIds 为空时【删光这个歌单的所有行】：歌单被清空了。
     * 不能直接拼 `NOT IN ()`——那是 SQL 语法错误。所以用 choose 分两支。
     */
    @Delete("""
            <script>
            DELETE FROM user_playlist_track
             WHERE import_id = #{importId}
            <if test="keepExternalIds != null and keepExternalIds.size() > 0">
               AND external_id NOT IN
               <foreach collection="keepExternalIds" item="e" open="(" separator="," close=")">#{e}</foreach>
            </if>
            </script>
            """)
    int deleteMissing(@Param("importId") Long importId,
                      @Param("keepExternalIds") List<String> keepExternalIds);

    /**
     * 我导入过的歌单，**带可分析曲目数**（见 UserPlaylistImport.matchedCount）。
     *
     * matched_count 的判据必须和 agent-service 的 resolve_user 完全一致 ——
     * match_status='MATCHED' 且 user_removed=0。对不上的话，下拉里显示
     * 「427 首可分析」而分析出来是 0 首，那种不一致用户会当成系统坏了。
     */
    @Select("""
            SELECT i.id, i.provider, i.external_playlist_id, i.playlist_name, i.source_url,
                   i.track_count, i.last_imported_at,
                   (SELECT COUNT(DISTINCT t.matched_track_id)
                      FROM user_playlist_track t
                     WHERE t.import_id = i.id
                       AND t.match_status = 'MATCHED'
                       AND t.matched_track_id IS NOT NULL
                       AND t.user_removed = 0) AS matched_count
            FROM user_playlist_import i
            WHERE i.user_id = #{userId}
            ORDER BY i.last_imported_at DESC
            """)
    List<UserPlaylistImport> listImports(@Param("userId") Long userId);

    /**
     * 分页取曲目。
     *
     * favorited 用 LEFT JOIN favorite_track 算，而不是让前端再拉一次
     * /api/favorites/ids 全量比对——那样在有几千首收藏时每次翻页都要传一大坨 id。
     * 条件是 ft.user_id = u.user_id，不是只比 track_id，否则会串到别人的收藏。
     *
     * filter 三选一：all（默认）/ matched / unmatched。
     * 【必须在 SQL 里筛，不能给前端在当页里过滤】——总行数和分页都在服务端算，
     * 前端只筛当页的话，「未收录」第二页会显示成第一页的补集，页码也是错的。
     */
    @Select("""
            <script>
            SELECT u.id, u.external_id, u.position, u.title, u.artists, u.album_name,
                   u.duration_ms, u.cover_url, u.match_status, u.matched_track_id,
                   (ft.id IS NOT NULL) AS favorited,
                   EXISTS(SELECT 1 FROM track_audio_feature f
                          WHERE f.track_id = u.matched_track_id
                            AND f.preview_url IS NOT NULL
                            AND f.preview_url &lt;&gt; '') AS has_preview
            FROM user_playlist_track u
            LEFT JOIN favorite_track ft
                   ON ft.user_id = u.user_id AND ft.track_id = u.matched_track_id
            WHERE u.import_id = #{importId} AND u.user_removed = 0
            <if test="filter == 'matched'">AND u.match_status = 'MATCHED'</if>
            <if test="filter == 'unmatched'">AND u.match_status &lt;&gt; 'MATCHED'</if>
            ORDER BY u.position
            LIMIT #{offset}, #{size}
            </script>
            """)
    List<ImportedTrackVO> selectTracks(@Param("importId") Long importId,
                                       @Param("offset") int offset,
                                       @Param("size") int size,
                                       @Param("filter") String filter);

    /**
     * 总数。user_removed = 1 的是被用户剔除的，不能再算进总数，否则页码和列表对不上。
     *
     * filter 口径必须和 selectTracks 完全一致，否则页码会和列表对不上。
     */
    @Select("""
            <script>
            SELECT COUNT(*) FROM user_playlist_track
            WHERE import_id = #{importId} AND user_removed = 0
            <if test="filter == 'matched'">AND match_status = 'MATCHED'</if>
            <if test="filter == 'unmatched'">AND match_status &lt;&gt; 'MATCHED'</if>
            </script>
            """)
    int countTracks(@Param("importId") Long importId, @Param("filter") String filter);

    /** 各对齐状态的数量，用于页面顶部「已收录 137 / 814」。口径必须和 countTracks 一致 */
    @Select("""
            SELECT match_status AS matchStatus, COUNT(*) AS cnt
            FROM user_playlist_track
            WHERE import_id = #{importId} AND user_removed = 0
            GROUP BY match_status
            """)
    List<java.util.Map<String, Object>> countByStatus(@Param("importId") Long importId);

    /**
     * 删整个歌单。
     *
     * user_playlist_track 那边靠外键 ON DELETE CASCADE 自动清，不必手动删第二张表
     * ——手动删反而容易漏。带 user_id 条件是防止删别人的：传别人的 id 会返回 0 行。
     */
    @Delete("DELETE FROM user_playlist_import WHERE id = #{id} AND user_id = #{userId}")
    int deleteImport(@Param("id") Long id, @Param("userId") Long userId);

    /**
     * 从歌单里剔除一首。软删除。
     *
     * 真删的话，下次重新导入时这首歌还在平台歌单里，upsert 会把它插回来，
     * 等于白剔。存个标记，upsert 时【不碰这一列】，就不会复活。
     *
     * 【WHERE 里必须带 user_removed = 0】——JDBC 默认 useAffectedRows=false，
     * UPDATE 返回的是「匹配到的行数」而不是「真正改变的行数」，
     * 对已经剔除过的行再执行一次照样返回 1，调用方就没法用返回值判断 404 了。
     * 加上这个条件，重复剔除会匹配 0 行，语义也更准：只能剔除还看得见的歌。
     */
    @Update("""
            UPDATE user_playlist_track SET user_removed = 1
             WHERE id = #{trackRowId} AND import_id = #{importId} AND user_removed = 0
            """)
    int markRemoved(@Param("importId") Long importId,
                    @Param("trackRowId") Long trackRowId);

    /** 这个歌单里已对齐、可以收藏的曲目（本地 track_id，已去重） */
    @Select("""
            SELECT DISTINCT matched_track_id
            FROM user_playlist_track
            WHERE import_id = #{importId} AND user_removed = 0
              AND match_status = 'MATCHED' AND matched_track_id IS NOT NULL
            """)
    List<Long> selectMatchedTrackIds(@Param("importId") Long importId);

    /**
     * 这个歌单里【当前】已对齐的行（externalId → trackId）。
     *
     * 重新导入前先拉进内存，用来做「对齐只前进不倒退」：
     * 加了时长校验之后，某些原本靠「名字 + 艺人」硬对上的行会被新规则拒掉，
     * 不该因为一次重导入就把用户已经能收藏的歌打回不可用。
     */
    @Select("""
            SELECT external_id AS externalId, matched_track_id AS trackId
            FROM user_playlist_track
            WHERE import_id = #{importId}
              AND match_status = 'MATCHED' AND matched_track_id IS NOT NULL
            """)
    List<java.util.Map<String, Object>> selectMatchedByExternalId(@Param("importId") Long importId);

    // ============================================================
    // 按需入库（③）
    // ============================================================

    /**
     * 按 id 取一行，同时校验归属。
     *
     * id 是自增的，别人猜一个就能把任务排到别人歌单里的歌上——
     * 前端不显示入口不等于安全。查不到（不属于本人 / 已剔除）就当作不存在。
     */
    @Select("""
            SELECT id, import_id, user_id, provider, external_id, position, title, artists,
                   album_name, duration_ms, cover_url, match_status, matched_track_id
            FROM user_playlist_track
            WHERE id = #{id} AND user_id = #{userId} AND user_removed = 0
            """)
    UserPlaylistTrack findTrackRow(@Param("id") Long id, @Param("userId") Long userId);

    /** 整个歌单里还没对齐的曲目，按歌单顺序（整单排队入库用） */
    @Select("""
            SELECT id, import_id, user_id, provider, external_id, position, title, artists,
                   album_name, duration_ms, cover_url, match_status, matched_track_id
            FROM user_playlist_track
            WHERE import_id = #{importId} AND user_removed = 0
              AND match_status <> 'MATCHED'
            ORDER BY position
            """)
    List<UserPlaylistTrack> selectNotMatchedByImport(@Param("importId") Long importId);
}
