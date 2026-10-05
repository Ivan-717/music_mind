package com.musicmind.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.List;

/**
 * 用一批曲目直接建一张歌单。给 Agent 的推荐用（「存成歌单」按钮）。
 *
 * 【为什么不分两步】前端先 create 再 N 次 addTrack 的话，中途失败会留下一张
 * 半空的歌单，而用户看到的是「保存失败」—— 他分不清是没建成还是建了没灌满。
 */
@Data
public class PlaylistFromTracksRequest {

    @NotBlank(message = "歌单名不能为空")
    @Size(max = 100, message = "歌单名最长 100 字")
    private String name;

    @NotEmpty(message = "没有指定曲目")
    @Size(max = 100, message = "一次最多 100 首")
    private List<Long> trackIds;
}
