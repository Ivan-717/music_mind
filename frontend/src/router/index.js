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
  routes
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
