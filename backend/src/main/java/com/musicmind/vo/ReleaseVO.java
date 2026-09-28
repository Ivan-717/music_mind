package com.musicmind.vo;

import lombok.Data;
import java.time.LocalDate;

@Data
public class ReleaseVO {
    private Long releaseId;
    private String title;
    private LocalDate releaseDate;
    private String country;
    private String status;
    private Integer trackCount;
}
