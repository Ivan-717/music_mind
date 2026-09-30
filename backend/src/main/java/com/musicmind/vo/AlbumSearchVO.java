package com.musicmind.vo;

import lombok.Data;

import java.time.LocalDate;

@Data
public class AlbumSearchVO {
    private Long id;
    private String name;
    private LocalDate releaseDate;
    private String artistNames;
}
