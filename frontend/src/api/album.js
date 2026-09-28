import http from './http'

export const apiAlbumDetail = (id) => http.get(`/albums/${id}`)

// releaseId 不传时后端会用最早发行的版本
export const apiAlbumTracks = (albumId, releaseId) =>
  http.get(`/albums/${albumId}/tracks`, {
    params: releaseId == null ? {} : { releaseId }
  })
