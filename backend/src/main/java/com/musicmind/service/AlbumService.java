package com.musicmind.service;

import com.musicmind.mapper.AlbumMapper;
import com.musicmind.vo.AlbumVO;
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
}
