package com.musicmind.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("favorite_track")
public class FavoriteTrack {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private Long trackId;

    // 不设值，交给 MySQL 的 DEFAULT CURRENT_TIMESTAMP
    private LocalDateTime createdAt;
}