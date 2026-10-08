package com.musicmind.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface PlayHistoryMapper {

    /**
     * 记一条试听。**append-only，只插不改**（表的设计如此）。
     *
     * played_ms 第一版恒 0 —— 前端在「开始播」时报，拿不到最终听了多久。
     * 要精确时长是以后的事（播放条关闭/切歌时补报一条），别在这张表上 UPDATE。
     *
     * track_id 有外键：脏 id 会抛 DataIntegrityViolation，由 service 吞掉 ——
     * 上报接口不该因为一条脏数据给用户弹错误。
     */
    @Insert("""
            INSERT INTO play_history (user_id, track_id, source, played_ms)
            VALUES (#{userId}, #{trackId}, #{source}, 0)
            """)
    int insertListen(@Param("userId") Long userId,
                     @Param("trackId") Long trackId,
                     @Param("source") String source);
}
