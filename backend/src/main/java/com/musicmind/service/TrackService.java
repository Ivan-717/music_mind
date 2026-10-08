package com.musicmind.service;

import com.musicmind.exception.ApiException;
import com.musicmind.mapper.TrackAudioFeatureMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class TrackService {

    private final TrackAudioFeatureMapper trackAudioFeatureMapper;

    /**
     * 30 秒试听的 URL。
     *
     * 「这首没有试听」在数据上完全正常（九成的歌都没有），但接口语义上
     * 用 404 表达 —— 前端把 404 显示成「试听暂时不可用」，和「URL 过期」
     * 走同一个兜底，不需要区分（都是「现在放不了」）。
     */
    public String previewUrl(Long trackId) {
        String url = trackAudioFeatureMapper.selectPreviewUrl(trackId);
        if (url == null || url.isBlank()) {
            throw new ApiException(404, "这首曲目没有试听");
        }
        return url;
    }
}