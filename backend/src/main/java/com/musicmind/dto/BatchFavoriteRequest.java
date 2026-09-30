package com.musicmind.dto;

import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.List;

/**
 * 批量收藏 / 批量取消收藏。
 *
 * trackIds 是【本地 track 表的 id】，不是导入歌单里那一行的 id。
 * 上限 500：一张歌单几百首是常态，但没上限的话一个请求就能塞几万个 id
 * 进来，SQL 的 IN 列表会撑爆（MySQL 有 max_allowed_packet）。
 */
@Data
public class BatchFavoriteRequest {

    @NotEmpty(message = "trackIds 不能为空")
    @Size(max = 500, message = "一次最多 500 首")
    private List<Long> trackIds = List.of();
}
