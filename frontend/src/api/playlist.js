import http from './http'

/**
 * 用户自己建的歌单（**和「导入的外歌单」不是一回事**）。
 *
 * 导入的歌单走 `/import/*`，那是「把外部的一份列表搬进来」；
 * 这里是「我在这个站上编的歌单」，可以增删改、可以公开。
 */

/** 我建过的歌单 */
export const apiMyPlaylists = () => http.get('/playlists')

/**
 * 用一批曲目直接建一张歌单。返回 { id, name, added, skipped }
 *
 * 【为什么不分两步】先 create 再逐个 addTrack 的话，中途失败会留下一张半空的
 * 歌单，而用户看到的是「保存失败」—— 他分不清是没建成还是建了没灌满。
 * 后端一次做完（`PlaylistService.createWithTracks`）。
 */
export const apiCreatePlaylistFromTracks = (name, trackIds) =>
  http.post('/playlists/from-tracks', { name, trackIds })

/** 一张自建歌单的曲目。无分页（自建歌单 ≤20 首，一次推荐的长度） */
export const apiPlaylistTracks = (id) => http.get(`/playlists/${id}/tracks`)

/** 改名（description/isPublic 后端支持，v1 不用） */
export const apiRenamePlaylist = (id, name) =>
  http.put(`/playlists/${id}`, { name })

export const apiDeletePlaylist = (id) => http.delete(`/playlists/${id}`)

/** 从歌单里移除一首 */
export const apiRemovePlaylistTrack = (playlistId, trackId) =>
  http.delete(`/playlists/${playlistId}/tracks/${trackId}`)
