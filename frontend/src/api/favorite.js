import http from './http'

// 分页取收藏列表 -> { total, page, size, items }
export const apiFavoritePage = (page = 1, size = 10) =>
  http.get('/favorites', { params: { page, size } })

// 取消收藏（幂等，重复取消也返回 204）
export const apiUnfavorite = (trackId) =>
  http.delete(`/favorites/${trackId}`)

// 收藏（幂等，重复收藏也返回 201）—— 6c 不用，第 7 步会用
export const apiFavorite = (trackId) =>
  http.post(`/favorites/${trackId}`)

// 当前用户全部收藏的 trackId，用于判断「这首歌是否已收藏」
export const apiFavoriteIds = () => http.get('/favorites/ids')

/**
 * 批量加入收藏。trackIds 是【本地 track 表的 id】，一次最多 500。
 * 返回 { changed, unknown }——unknown 是本地库里没有的 id（已跳过），
 * 正常情况应该是 0，不为 0 说明传了脏 id。
 */
export const apiFavoriteBatch = (trackIds) =>
  http.post('/favorites/batch', { trackIds })

/** 批量取消收藏。同样返回 { changed, unknown } */
export const apiUnfavoriteBatch = (trackIds) =>
  http.post('/favorites/batch/remove', { trackIds })
