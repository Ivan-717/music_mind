package com.musicmind.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("app_user")
public class AppUser {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String username;
    private String passwordHash;   // 靠 application.yaml 的 map-underscore-to-camel-case 映射到 password_hash
    private String nickname;
    private String avatarUrl;
    private String email;
    private Integer status;
    // getter / setter 用 Lombok @Data
}
