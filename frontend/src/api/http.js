import axios from 'axios'
import { useUserStore } from '@/stores/user'

const http = axios.create({
  baseURL: '/api',
  timeout: 10000
})

// 请求拦截器：自动带 token
http.interceptors.request.use((config) => {
  // 注意：useUserStore() 必须在函数内部调用，不能在模块顶层
  const store = useUserStore()
  if (store.token) {
    config.headers.Authorization = 'Bearer ' + store.token
  }
  return config
})

// 响应拦截器：401 统一登出
http.interceptors.response.use(
  // 成功时直接吐 data，组件里不用再写 .data
  (res) => res.data,
  (err) => {
    if (err.response?.status === 401) {
      const store = useUserStore()
      store.clear()
      // 用 location 而非 router.push：
      // 1) 避免 http.js ↔ router 循环依赖
      // 2) 整页刷新能清干净所有内存状态
      window.location.replace('/login')
    }
    return Promise.reject(err)
  }
)

export default http
