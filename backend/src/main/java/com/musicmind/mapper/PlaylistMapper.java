package com.musicmind.mapper;

import com.musicmind.entity.Playlist;
import com.musicmind.vo.PlaylistTrackVO;
import com.musicmind.vo.PlaylistVO;
import org.apache.ibatis.annotations.*;

import java.util.List;

@Mapper
public interface PlaylistMapper {

    @Select("""
            SELECT p.id, p.name, p.description, p.is_public,
                   p.created_at, p.updated_at,
                   (SELECT COUNT(*) FROM playlist_track pt WHERE pt.playlist_id = p.id) AS track_count
            FROM playlist p
            WHERE p.user_id = #{userId}
            ORDER BY p.updated_at DESC, p.id DESC
            """)
    List<PlaylistVO> selectByUser(@Param("userId") Long userId);

    @Select("""
            SELECT p.id, p.name, p.description, p.is_public,
                   p.created_at, p.updated_at,
                   (SELECT COUNT(*) FROM playlist_track pt WHERE pt.playlist_id = p.id) AS track_count
            FROM playlist p
            WHERE p.id = #{id} AND p.user_id = #{userId}
            """)
    PlaylistVO selectDetail(@Param("id") Long id, @Param("userId") Long userId);

    // 归属校验的唯一入口；返回 0 表示不存在或不属于该用户
    @Select("SELECT COUNT(*) FROM playlist WHERE id = #{id} AND user_id = #{userId}")
    int countOwned(@Param("id") Long id, @Param("userId") Long userId);

    @Insert("""
            INSERT INTO playlist (user_id, name, description, is_public)
            VALUES (#{userId}, #{name}, #{description}, #{isPublic})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(Playlist p);

    @Update("""
            UPDATE playlist
               SET name = #{name}, description = #{description}, is_public = #{isPublic}
             WHERE id = #{id} AND user_id = #{userId}
            """)
    int update(@Param("id") Long id, @Param("userId") Long userId,
               @Param("name") String name, @Param("description") String description,
               @Param("isPublic") Boolean isPublic);

    @Delete("DELETE FROM playlist WHERE id = #{id} AND user_id = #{userId}")
    int delete(@Param("id") Long id, @Param("userId") Long userId);

    @Select("""
            SELECT pt.track_id, pt.sort_order, pt.added_at,
                   t.name, t.duration_ms,
                   a.id AS album_id, a.name AS album_name,
                   GROUP_CONCAT(
                       CONCAT(COALESCE(ta.credited_name, ar.name), COALESCE(ta.join_phrase, ''))
                       ORDER BY ta.id SEPARATOR ''
                   ) AS artist_names
            FROM playlist_track pt
            JOIN track t              ON t.id = pt.track_id
            LEFT JOIN album a         ON a.id = (
                    SELECT mr2.album_id
                    FROM release_track rt2
                    JOIN music_release mr2 ON mr2.id = rt2.release_id
                    WHERE rt2.track_id = t.id
                    ORDER BY mr2.release_date IS NULL, mr2.release_date, mr2.id
                    LIMIT 1)
            LEFT JOIN track_artist ta ON ta.track_id = t.id
            LEFT JOIN artist ar       ON ar.id = ta.artist_id
            WHERE pt.playlist_id = #{playlistId}
            GROUP BY pt.id, pt.track_id, pt.sort_order, pt.added_at, t.name, t.duration_ms, a.id, a.name
            ORDER BY pt.sort_order
            """)
    List<PlaylistTrackVO> selectTracks(@Param("playlistId") Long playlistId);

    /**
     * 这批 id 里哪些在库里真实存在。
     *
     * 【先查再插，不靠外键抛异常】用 try/catch DataIntegrityViolationException
     * 来「跳过脏 id」的话，异常会把事务搅浑，而且「跳过几个」和「整张失败」
     * 这两种结果混在一起，调用方分不出来。
     */
    @Select("""
            <script>
            SELECT id FROM track WHERE id IN
            <foreach collection="ids" item="i" open="(" separator="," close=")">#{i}</foreach>
            </script>
            """)
    List<Long> selectExistingTrackIds(@Param("ids") List<Long> ids);

    // sort_order 自动取当前最大值 +1；重复加同一首不报错也不改顺序
    @Insert("""
            INSERT INTO playlist_track (playlist_id, track_id, sort_order)
            SELECT #{playlistId}, #{trackId}, COALESCE(MAX(sort_order), 0) + 1
            FROM playlist_track
            WHERE playlist_id = #{playlistId}
            ON DUPLICATE KEY UPDATE id = id
            """)
    int addTrack(@Param("playlistId") Long playlistId, @Param("trackId") Long trackId);

    @Delete("DELETE FROM playlist_track WHERE playlist_id = #{playlistId} AND track_id = #{trackId}")
    int removeTrack(@Param("playlistId") Long playlistId, @Param("trackId") Long trackId);
}
