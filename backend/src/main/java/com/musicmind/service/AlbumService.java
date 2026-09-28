package com.musicmind.service;

import com.musicmind.exception.ApiException;
import com.musicmind.mapper.AlbumMapper;
import com.musicmind.vo.AlbumDetailVO;
import com.musicmind.vo.AlbumTrackVO;
import com.musicmind.vo.AlbumVO;
import com.musicmind.vo.ReleaseVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class AlbumService {

    private final AlbumMapper albumMapper;

    public List<AlbumVO> listAlbums() {
        return albumMapper.selectAlbumList();
    }

    //查询专辑基本信息
    public AlbumDetailVO detail(Long albumId) {
        AlbumDetailVO vo = albumMapper.selectAlbumDetail(albumId);
        if (vo == null) {
            throw new ApiException(404, "专辑不存在");
        }
        vo.setReleases(albumMapper.selectReleases(albumId));
        return vo;
    }

    //查询专辑曲目
    public List<AlbumTrackVO> tracks(Long albumId, Long releaseId) {
        if (albumMapper.countById(albumId) == 0) {
            throw new ApiException(404, "专辑不存在");
        }
        List<ReleaseVO> rels = albumMapper.selectReleases(albumId);

        if (releaseId == null) {
            // 不传就用最早发行的那个版本
            if (rels.isEmpty()) {
                return List.of();          // 专辑存在但没有任何 release
            }
            releaseId = rels.get(0).getReleaseId();
        } else {
            // 必须校验这个 release 真属于这张专辑，
            // 否则 /albums/12/tracks?releaseId=<别的专辑的id> 能越权读到别人的曲目
            Long target = releaseId;
            boolean belongs = rels.stream()
                    .anyMatch(r -> r.getReleaseId().equals(target));
            if (!belongs) {
                throw new ApiException(404, "该版本不属于此专辑");
            }
        }

        return albumMapper.selectTracksByRelease(releaseId);
    }

}
