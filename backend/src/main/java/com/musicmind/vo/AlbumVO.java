package com.musicmind.vo;

import lombok.Data;
import java.time.LocalDate;

@Data
public class AlbumVO {
    private Long id;
    private String name;
    private LocalDate releaseDate;
    private String primaryType;
    private String artistNames;
}
