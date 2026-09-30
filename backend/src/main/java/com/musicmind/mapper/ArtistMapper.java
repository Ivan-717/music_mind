package com.musicmind.mapper;

import com.musicmind.vo.ArtistAlbumVO;
import com.musicmind.vo.ArtistDetailVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface
ArtistMapper {

    @Select("""
            SELECT a.id, a.name, a.sort_name, a.disambiguation
            FROM artist a
            WHERE a.id = #{id}
            """)
    ArtistDetailVO selectDetail(@Param("id") Long id);

    @Select("""
            SELECT al.name
            FROM artist_alias al
            WHERE al.artist_id = #{id}
            ORDER BY al.is_primary DESC, al.locale, al.name
            """)
    List<String> selectAliases(@Param("id") Long id);

    @Select("""
            SELECT g.name
            FROM artist_genre ag
            JOIN genre g ON g.id = ag.genre_id
            WHERE ag.artist_id = #{id}
            ORDER BY ag.weight DESC, g.name
            """)
    List<String> selectGenres(@Param("id") Long id);

    /**
     * 该歌手的专辑列表。
     *
     * trackCount 取【默认版本】（最早发行的那个 release）的曲目数——
     * 用跨所有 release 去重的并集会虚高，而且和专辑详情页对不上。
     * 口径必须和 AlbumMapper.selectReleases() 的第一条一致。
     */
    @Select("""
            SELECT a.id, a.name, a.release_date, a.primary_type,
                   (SELECT COUNT(*) FROM release_track rt
                    WHERE rt.release_id = (
                        SELECT mr2.id FROM music_release mr2
                        WHERE mr2.album_id = a.id
                        ORDER BY mr2.release_date IS NULL, mr2.release_date, mr2.id
                        LIMIT 1)) AS track_count
            FROM album a
            JOIN album_artist aa ON aa.album_id = a.id
            WHERE aa.artist_id = #{id}
            ORDER BY a.release_date IS NULL, a.release_date, a.id
            """)
    List<ArtistAlbumVO> selectAlbums(@Param("id") Long id);

    /** 该歌手出现过的曲目总数（去重） */
    @Select("""
            SELECT COUNT(DISTINCT ta.track_id)
            FROM track_artist ta
            WHERE ta.artist_id = #{id}
            """)
    int countTracks(@Param("id") Long id);

    /**
     * 按 MusicBrainz ID 找本地 id。找不到返回 null。
     * 用于 MusicBrainz 查询结果里标注「这条本地已经导入过了」。
     */
    @Select("SELECT id FROM artist WHERE musicbrainz_id = #{mbid}")
    Long selectIdByMbid(@Param("mbid") String mbid);
}
