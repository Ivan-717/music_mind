package com.musicmind.vo;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

@Data
public class ImportedPlaylistVO {
    private Long importId;
    private String provider;
    private String playlistName;
    private String sourceUrl;
    private int total;
    private int page;
    private int size;
    /** 各对齐状态的数量，前端拿去显示「已识别 137 / 814」 */
    private int matchedCount;
    private int pendingCount;
    private int unresolvedCount;
    /** 本页用的筛选：all / matched / unmatched。回给前端是为了让前端不必自己猜服务端认了什么 */
    private String filter = "all";
    private List<ImportedTrackVO> items = List.of();
    private LocalDateTime lastImportedAt;
}
