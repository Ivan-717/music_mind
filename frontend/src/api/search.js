import http from './http'

// 一次请求返回三类结果：
// { keyword, variants, trackTotal, albumTotal, artistTotal, tracks, albums, artists }
//
// limit 是三类的【每类】上限（后端上限 100）。
// 给 50 而不是后端默认的 20：搜索结果页用户会滚动，多给一些，
// 剩下的数量靠 total 字段如实告诉用户。
export const apiSearch = (q, limit = 50) =>
  http.get('/search', { params: { q, limit } })
