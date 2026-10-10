package com.musicmind.service;

import com.musicmind.mapper.SearchMapper;
import com.musicmind.mapper.UserPlaylistMapper;
import com.musicmind.util.KeywordVariants;
import com.musicmind.vo.SearchVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class SearchService {

    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 100;

    private final SearchMapper searchMapper;
    private final UserPlaylistMapper userPlaylistMapper;

    public SearchVO search(String keyword, Integer limit, Long userId) {
        SearchVO vo = new SearchVO();
        vo.setKeyword(keyword);

        List<String> variants = KeywordVariants.of(keyword);
        vo.setVariants(variants);

        // 空关键词直接返回空结果，不打库
        if (variants.isEmpty()) {
            return vo;
        }

        int size = (limit == null || limit < 1) ? DEFAULT_LIMIT : Math.min(limit, MAX_LIMIT);

        String v1 = KeywordVariants.at(variants, 0);
        String v2 = KeywordVariants.at(variants, 1);
        String v3 = KeywordVariants.at(variants, 2);

        vo.setTracks(searchMapper.searchTracks(v1, v2, v3, size));
        vo.setAlbums(searchMapper.searchAlbums(v1, v2, v3, size));
        vo.setArtists(searchMapper.searchArtists(v1, v2, v3, size));

        // 总数单独查。不这么做的话，搜「周杰伦」只返回 20 条，
        // 前端没法告诉用户「其实有 780 首」——那是误导。
        vo.setTrackTotal(searchMapper.countTracks(v1, v2, v3));
        vo.setAlbumTotal(searchMapper.countAlbums(v1, v2, v3));
        vo.setArtistTotal(searchMapper.countArtists(v1, v2, v3));

        // 第二来源：我歌单里还没入库的（MB 覆盖差的中文歌往往在这儿，
        // 搜不到 → 搜得到、看得见状态、能试听）
        vo.setPlaylistHits(userPlaylistMapper.searchUnmatched(userId, v1, v2, v3));

        return vo;
    }
}
