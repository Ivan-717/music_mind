import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiLogin, apiMe } from '@/api/auth'

const TOKEN_KEY = 'mm_token'

export const useUserStore = defineStore('user', () => {
  // 初始化时从 localStorage 恢复 —— 刷新页面登录态不丢
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref(null)

  function clear() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
  }

  function setToken(t) {
    token.value = t
    localStorage.setItem(TOKEN_KEY, t)
  }

  async function login(username, password) {
    // 后端 /auth/login 直接返回 { token, tokenType, expiresIn, user }
    const data = await apiLogin(username, password)
    setToken(data.token)
    user.value = data.user
  }

  async function fetchMe() {
    user.value = await apiMe()
  }

  return { token, user, login, setToken, clear, fetchMe }
})
