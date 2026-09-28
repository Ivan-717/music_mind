package com.musicmind.vo;

import lombok.Data;
import java.time.LocalDate;
import java.util.List;

@Data
public class AlbumDetailVO {
    private Long id;
    private String name;
    private LocalDate releaseDate;
    private String primaryType;
    private String artistNames;
    private List<ReleaseVO> releases;   // 由 Service 填充
}
