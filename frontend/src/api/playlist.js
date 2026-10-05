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
