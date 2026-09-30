package com.musicmind.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class PlaylistRequest {

    @NotBlank(message = "歌单名不能为空")
    @Size(max = 255, message = "歌单名最长 255 字")
    private String name;

    @Size(max = 1000, message = "描述最长 1000 字")
    private String description;

    private Boolean isPublic = false;
}
