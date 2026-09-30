import http from './http'

/**
 * 导入一个外部歌单。
 *
 * @param url      歌单链接
 * @param favorite 是否顺手把这批歌加进收藏。【默认 false】——
 *                 导入是搬列表，收藏是表态，不默认替用户做决定。
 *
 * 这个接口【会落库】：歌单和每一首都被存进 user_playlist_import /
 * user_playlist_track，导入完可以直接去「我的歌单」页看全部曲目。
 * 重复导入同一个歌单是更新，不会产生第二份。
 */
export const apiImportPlaylist = (url, favorite = false) =>
  http.post('/import/playlist', { url, favorite })

/** 我导入过的歌单列表（按最近导入时间倒序） */
export const apiListImports = () =>
  http.get('/import/playlists')

/**
 * 某个导入歌单的曲目，分页。
 *
 * 返回 { importId, provider, playlistName, total, page, size,
 *        matchedCount, pendingCount, unresolvedCount, items, lastImportedAt }
 *
 * items 里每项带：
 *   id              user_playlist_track 那一行的 id（剔除时用它）
 *   matchedTrackId  对齐到的本地曲目 id，没对齐是 null（收藏时用它）
 *   favorited       当前用户收藏了没有
 * 被剔除（user_removed=1）的不会返回，也不计入 total。
 *
 * filter: 'all'（默认）/ 'matched' / 'unmatched'。
 * 【必须在服务端筛】——total 和分页都在服务端算，前端只筛当页的话，
 * 「未收录」第二页会显示成第一页的补集，页码也是错的。
 * matchedCount / pendingCount / unresolvedCount 三个计数【始终是全量】，
 * 不跟着 filter 走，这样筛到「已收录」时还看得见还剩多少要抓。
 */
export const apiImportTracks = (importId, page = 1, size = 50, filter = 'all') =>
  http.get(`/import/playlists/${importId}/tracks`, { params: { page, size, filter } })

/** 删掉整个歌单。里面的曲目靠外键级联清掉，收藏不受影响 */
export const apiDeleteImport = (importId) =>
  http.delete(`/import/playlists/${importId}`)

/** 从歌单里剔除一首。软删除——下次重新导入也不会复活，收藏不受影响 */
export const apiRemoveImportTrack = (importId, trackRowId) =>
  http.delete(`/import/playlists/${importId}/tracks/${trackRowId}`)

/**
 * 把歌单里【已对齐】的歌全部加入收藏（一键整单，不用逐首勾）。
 * 返回 { added, alreadyFavorited, notMatched }——notMatched 是还没进本地库、
 * 收藏不了的，必须显示出来，否则用户以为整单都收藏上了。
 */
export const apiFavoriteAll = (importId) =>
  http.post(`/import/playlists/${importId}/favorite-all`)
