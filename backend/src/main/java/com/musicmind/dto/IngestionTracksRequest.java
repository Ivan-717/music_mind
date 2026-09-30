package com.musicmind.dto;

import lombok.Data;

import java.util.List;

/** 逐首入库的请求体：user_playlist_track 的行 id 列表 */
@Data
public class IngestionTracksRequest {

    private List<Long> trackRowIds;
}
