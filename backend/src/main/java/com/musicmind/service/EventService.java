package com.musicmind.service;

import com.musicmind.mapper.PlayHistoryMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

import java.util.Set;

/**
 * 行为事件（试听上报，2026-10-08）。
 *
 * 【为什么静默】这是 fire-and-forget 的埋点接口：脏数据、不存在的 track、
 * 前端塞的非法 source —— 全都安静丢掉。**上报失败不值得打扰用户**，
 * 下一条行为会补上。日志也不打 —— 一次误报刷一行日志比丢一条事件更烦。
 *
 * 【为什么 source 是白名单】分析时只有 report 来源算「推荐被采纳」，
 * 前端要是能塞任意字符串（或空），那个口径就废了。
 */
@Service
@RequiredArgsConstructor
public class EventService {

    private static final Set<String> SOURCES = Set.of(
            "report", "album", "playlist", "search", "favorite", "artist", "chat", "other");

    private final PlayHistoryMapper playHistoryMapper;

    public void listen(Long userId, Long trackId, String source) {
        if (userId == null || trackId == null || trackId <= 0
                || source == null || !SOURCES.contains(source)) {
            return;
        }
        try {
            playHistoryMapper.insertListen(userId, trackId, source);
        } catch (DataIntegrityViolationException ignored) {
            // track_id 外键没对上 —— 静默（见类注释）
        }
    }
}
