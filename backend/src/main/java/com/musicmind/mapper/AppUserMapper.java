package com.musicmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.musicmind.entity.AppUser;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface AppUserMapper extends BaseMapper<AppUser> {
}
