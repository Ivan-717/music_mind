package com.musicmind.mapper;

import com.musicmind.vo.AlbumDetailVO;
import com.musicmind.vo.AlbumTrackVO;
import com.musicmind.vo.AlbumVO;
import com.musicmind.vo.ReleaseVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface AlbumMapper {

    @Select("""
            SELECT a.id,
                   a.name,
                   a.release_date,
                   a.primary_type,
                   GROUP_CONCAT(
                       CONCAT(COALESCE(aa.credited_name, ar.name),
                              COALESCE(aa.join_phrase, ''))
                       ORDER BY aa.id SEPARATOR ''
                   ) AS artist_names
            FROM album a
            LEFT JOIN album_artist aa ON aa.album_id = a.id
            LEFT JOIN artist ar       ON ar.id = aa.artist_id
            GROUP BY a.id
            ORDER BY a.release_date DESC
            """)
    List<AlbumVO> selectAlbumList();

    @Select("SELECT COUNT(*) FROM album WHERE id = #{id}")
    int countById(@Param("id") Long id);

    @Select("""
            SELECT a.id, a.name, a.release_date, a.primary_type,
                   GROUP_CONCAT(
                       CONCAT(COALESCE(aa.credited_name, ar.name),
                              COALESCE(aa.join_phrase, ''))
                       ORDER BY aa.id SEPARATOR ''
                   ) AS artist_names
            FROM album a
            LEFT JOIN album_artist aa ON aa.album_id = a.id
            LEFT JOIN artist ar       ON ar.id = aa.artist_id
            WHERE a.id = #{id}
            GROUP BY a.id, a.name, a.release_date, a.primary_type
            """)
    AlbumDetailVO selectAlbumDetail(@Param("id") Long id);

    @Select("""
            SELECT mr.id AS release_id,
                   mr.title,
                   mr.release_date,
                   mr.country,
                   mr.status,
                   (SELECT COUNT(*) FROM release_track rt WHERE rt.release_id = mr.id) AS track_count
            FROM music_release mr
            WHERE mr.album_id = #{albumId}
            ORDER BY mr.release_date IS NULL, mr.release_date, mr.id
            """)
    List<ReleaseVO> selectReleases(@Param("albumId") Long albumId);

    @Select("""
            SELECT rt.track_number,
                   rt.disc_number,
                   t.id          AS track_id,
                   t.name        AS name,
                   t.duration_ms AS duration_ms,
                   GROUP_CONCAT(
                       CONCAT(COALESCE(ta.credited_name, ar.name),
                              COALESCE(ta.join_phrase, ''))
                       ORDER BY ta.id SEPARATOR ''
                   ) AS artist_names
            FROM release_track rt
            JOIN track t              ON t.id = rt.track_id
            LEFT JOIN track_artist ta ON ta.track_id = t.id
            LEFT JOIN artist ar       ON ar.id = ta.artist_id
            WHERE rt.release_id = #{releaseId}
            GROUP BY rt.id, rt.track_number, rt.disc_number, t.id, t.name, t.duration_ms
            ORDER BY rt.disc_number, rt.track_number
            """)
    List<AlbumTrackVO> selectTracksByRelease(@Param("releaseId") Long releaseId);

}
