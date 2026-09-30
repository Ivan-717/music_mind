import http from './http'

export const apiLogin = (username, password) =>
  http.post('/auth/login', { username, password })

export const apiRegister = (username, password) =>
  http.post('/auth/register', { username, password })

export const apiAlbums = () => http.get('/albums')
