package com.musicmind.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class ImportRequest {

    @NotBlank(message = "歌单链接不能为空")
    private String url;

    /**
     * 导入时是否顺手把这批歌加进收藏。
     *
     * 【默认 false】——导入是「搬一份列表过来」，收藏是「我喜欢这首歌」，两件事。
     * 默认勾上等于每次导入都偷偷改用户的收藏。
     *
     * 不勾也没关系：歌单页里每首都能单独 ♡，也能勾一批批量收藏，
     * 还有「全部加入收藏」一键整单。
     */
    private boolean favorite = false;
}
