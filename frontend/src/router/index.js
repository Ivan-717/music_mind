import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes = [
  { path: '/', redirect: '/albums' },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true }        // 白名单：不需要登录
  },
  {
    path: '/albums',
    name: 'albums',
    component: () => import('@/views/AlbumListView.vue')
  },
    {
    path: '/favorites',
    name: 'favorites',
    component: () => import('@/views/FavoriteView.vue')
  },
      {
    path: '/albums/:id',
    name: 'album-detail',
    component: () => import('@/views/AlbumDetailView.vue')
  },
    {
    path: '/search',
    name: 'search',
    component: () => import('@/views/SearchView.vue')
  },
    {
    path: '/artists/:id',
    name: 'artist-detail',
    component: () => import('@/views/ArtistView.vue')
  },
    {
    path: '/import',
    name: 'import',
    component: () => import('@/views/ImportView.vue')
  },
    {
    path: '/my-playlist',
    name: 'my-playlist',
    component: () => import('@/views/MyPlaylistView.vue')
  },

  {
    path: '/explore',
    name: 'explore',
    component: () => import('@/views/ExploreView.vue')
  },

  {
    path: '/persona',
    name: 'persona',
    component: () => import('@/views/PersonaView.vue')
  },
  { path: '/:pathMatch(.*)*', redirect: '/albums' }
]

const router = createRouter({
  history: createWebHistory(),
  routes,

  /**
   * 【返回时回到原位置】savedPosition 只在浏览器后退/前进（popstate）时才有 ——
   * 「← 返回」按钮走的就是 router.back()，所以能吃到；点导航栏是新导航，
   * 滚到顶（保持原来的行为）。
   *
   * 【为什么要返回 Promise 等一等】列表页的数据是异步拉的：导航确认那一刻
   * 页面还是空的，scrollHeight 只有几百像素，直接滚到 1200px 会被浏览器
   * 夹回 0 —— 表现就是「点了返回，回到顶部」。
   * 所以每帧看一眼「目标位置到了没有」，够了再滚；最多等 1.5 秒，
   * 网络慢就退化成现在的行为（滚到尽可能远），不卡导航。
   */
  scrollBehavior(to, from, savedPosition) {
    if (!savedPosition) return { top: 0 }

    return new Promise((resolve) => {
      const deadline = Date.now() + 1500
      const tryScroll = () => {
        const tall = document.documentElement.scrollHeight
        if (tall >= savedPosition.top + window.innerHeight || Date.now() > deadline) {
          resolve(savedPosition)
        } else {
          requestAnimationFrame(tryScroll)
        }
      }
      requestAnimationFrame(tryScroll)
    })
  }
})

router.beforeEach((to) => {
  const store = useUserStore()

  // 未登录闯受保护页 -> 踢回登录，并记住原本要去哪
  if (!to.meta.public && !store.token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  // 已登录还去登录页 -> 送回专辑页
  if (to.meta.public && store.token) {
    return { path: '/albums' }
  }
})

export default router
