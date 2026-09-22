package com.musicmind.mapper;

import com.musicmind.vo.AlbumVO;
import org.apache.ibatis.annotations.Mapper;
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
}
