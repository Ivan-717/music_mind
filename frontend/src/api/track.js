import http from './http'

/**
 * 30 秒试听的 URL（iTunes 预览，浏览器直连 Apple，服务器不中转）。
 * 没有试听的曲目后端返回 404 —— 列表里靠 hasPreview 提前过滤，
 * 走到这里的 404 基本只有一种：preview_url 过期了。
 */
export const apiTrackPreview = (trackId) => http.get(`/tracks/${trackId}/preview`)
