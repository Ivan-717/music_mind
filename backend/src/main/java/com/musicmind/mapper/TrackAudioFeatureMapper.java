package com.musicmind.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface TrackAudioFeatureMapper {

    /** 没有记录 / 记录里 url 为空都返回 null，由 service 决定怎么表达 */
    @Select("SELECT preview_url FROM track_audio_feature WHERE track_id = #{trackId} LIMIT 1")
    String selectPreviewUrl(@Param("trackId") Long trackId);
}