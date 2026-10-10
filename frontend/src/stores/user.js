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

  /**
   * 刷新后把用户信息找回来（导航栏的用户名）。
   *
   * 【失败不清 token】一次网络抖动不该把人踢下线 ——
   * 真正的 401 由 http.js 的拦截器统一处理（清 token + 跳登录）。
   * 这里失败就当导航栏少个名字，不影响任何操作。
   */
  async function fetchMe() {
    if (!token.value || user.value) return
    try {
      user.value = await apiMe()
    } catch (e) {
      /* 静默，见上 */
    }
  }

  return { token, user, login, setToken, clear, fetchMe }
})
