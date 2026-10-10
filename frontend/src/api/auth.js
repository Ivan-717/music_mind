import http from './http'

export const apiLogin = (username, password) =>
  http.post('/auth/login', { username, password })

export const apiRegister = (username, password) =>
  http.post('/auth/register', { username, password })

/** 当前用户。刷新后恢复导航栏用户名用（user store 的 fetchMe 调它） */
export const apiMe = () => http.get('/auth/me')

export const apiAlbums = () => http.get('/albums')
