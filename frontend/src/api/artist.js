import http from './http'

// { id, name, sortName, disambiguation, aliases, genres, albumCount, trackCount, albums }
export const apiArtistDetail = (id) => http.get(`/artists/${id}`)

/**
 * 去 MusicBrainz 查歌手。只在本地搜不到时才调——它走后端到外网，比本地查询慢得多。
 * 返回 [{ mbid, name, score, country, type, disambiguation, localId }]
 * localId 非 null 表示本地库里已经有这个人。
 */
export const apiArtistLookup = (q, limit = 5) =>
  http.get('/artists/lookup', { params: { q, limit } })
