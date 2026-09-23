package com.musicmind.mapper;

import com.musicmind.vo.FavoriteTrackVO;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface FavoriteTrackMapper {

    @Insert("""
            INSERT INTO favorite_track (user_id, track_id)
            VALUES (#{userId}, #{trackId})
            ON DUPLICATE KEY UPDATE id = id
            """)
    int addFavorite(@Param("userId") Long userId, @Param("trackId") Long trackId);

    @Delete("DELETE FROM favorite_track WHERE user_id = #{userId} AND track_id = #{trackId}")
    int removeFavorite(@Param("userId") Long userId, @Param("trackId") Long trackId);

    @Select("SELECT COUNT(*) FROM favorite_track WHERE user_id = #{userId}")
    long countByUser(@Param("userId") Long userId);

    @Select("SELECT track_id FROM favorite_track WHERE user_id = #{userId}")
    List<Long> selectTrackIdsByUser(@Param("userId") Long userId);

    @Select("""
            SELECT t.id          AS track_id,
                   t.name        AS name,
                   t.duration_ms AS duration_ms,
                   ft.created_at AS favorited_at,
                   a.id          AS album_id,
                   a.name        AS album_name,
                   GROUP_CONCAT(
                       CONCAT(COALESCE(ta.credited_name, ar.name),
                              COALESCE(ta.join_phrase, ''))
                       ORDER BY ta.id SEPARATOR ''
                   ) AS artist_names
            FROM favorite_track ft
            JOIN track t              ON t.id = ft.track_id
            LEFT JOIN album a         ON a.id = (
                    SELECT mr2.album_id
                    FROM release_track rt2
                    JOIN music_release mr2 ON mr2.id = rt2.release_id
                    WHERE rt2.track_id = t.id
                    ORDER BY mr2.release_date IS NULL, mr2.release_date, mr2.id
                    LIMIT 1)
            LEFT JOIN track_artist ta ON ta.track_id = t.id
            LEFT JOIN artist ar       ON ar.id = ta.artist_id
            WHERE ft.user_id = #{userId}
            GROUP BY t.id, t.name, t.duration_ms, ft.created_at, a.id, a.name
            ORDER BY ft.created_at DESC, ft.id DESC
            LIMIT #{offset}, #{size}
            """)
    List<FavoriteTrackVO> selectFavoritePage(@Param("userId") Long userId,
                                             @Param("offset") int offset,
                                             @Param("size") int size);
}