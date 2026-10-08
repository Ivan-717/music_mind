import http from './http'

/**
 * 试听上报（fire-and-forget）。
 *
 * 【失败必须静默】埋点不值得打扰用户、也不值得重试 —— catch 掉，
 * 下一条行为会补上。后端也同一条哲学：白名单外的 source、不存在的
 * track 全部安静丢弃（见 EventService 的类注释）。
 */
export const apiReportListen = (trackId, source) =>
  http.post('/events/listen', { trackId, source }).catch(() => {})
