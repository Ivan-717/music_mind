package com.musicmind.service;

import com.musicmind.exception.ApiException;
import com.musicmind.mapper.ArtistMapper;
import com.musicmind.vo.ArtistAlbumVO;
import com.musicmind.vo.ArtistDetailVO;
import com.musicmind.vo.MbArtistVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class ArtistService {

    private static final int DEFAULT_LOOKUP_LIMIT = 5;
    private static final int MAX_LOOKUP_LIMIT = 10;

    private final ArtistMapper artistMapper;
    private final MusicBrainzLookupService musicBrainzLookupService;

    /**
     * 本地没有这位歌手时，去 MusicBrainz 看看上游有什么。
     * 只报告，不导入——抓取入库是 Python 管道的事。
     */
    public List<MbArtistVO> lookup(String keyword, Integer limit) {
        if (keyword == null || keyword.isBlank()) {
            return List.of();
        }
        int size = (limit == null || limit < 1)
                ? DEFAULT_LOOKUP_LIMIT
                : Math.min(limit, MAX_LOOKUP_LIMIT);
        return musicBrainzLookupService.searchArtists(keyword.trim(), size);
    }

    public ArtistDetailVO detail(Long artistId) {
        ArtistDetailVO vo = artistMapper.selectDetail(artistId);
        if (vo == null) {
            throw new ApiException(404, "歌手不存在");
        }

        vo.setAliases(artistMapper.selectAliases(artistId));
        vo.setGenres(artistMapper.selectGenres(artistId));

        List<ArtistAlbumVO> albums = artistMapper.selectAlbums(artistId);
        vo.setAlbums(albums);
        vo.setAlbumCount(albums.size());
        vo.setTrackCount(artistMapper.countTracks(artistId));

        return vo;
    }
}
