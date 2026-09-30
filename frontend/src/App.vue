<script setup>
import { ref, watch } from 'vue'
import { RouterView, RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useSettingsStore } from '@/stores/settings'

const settings = useSettingsStore()
const store = useUserStore()
const router = useRouter()
const route = useRoute()

const kw = ref('')

function doSearch() {
  const q = kw.value.trim()
  if (!q) return
  router.push({ path: '/search', query: { q } })
}

// 路由里的关键词回填到输入框：
// 这样从搜索结果页刷新、或点后退，输入框里还是刚才那个词
watch(
  () => route.query.q,
  (q) => { kw.value = q || '' },
  { immediate: true }
)

function logout() {
  store.clear()
  router.replace('/login')
}
</script>

<template>
  <header v-if="store.token">
    <nav>
      <RouterLink to="/albums">专辑</RouterLink>
      <RouterLink to="/favorites">我的收藏</RouterLink>
      <RouterLink to="/import">导入歌单</RouterLink>
      <RouterLink to="/my-playlist">我的歌单</RouterLink>
      <input
        v-model="kw"
        class="nav-search"
        type="search"
        placeholder="搜索歌曲 / 专辑 / 歌手"
        @keyup.enter="doSearch"
      />
      <span class="who">{{ store.user?.username || '' }}</span>
      <button @click="settings.toggle()">
        {{ settings.simplified ? '简' : '繁' }}
      </button>
      <button @click="logout">退出</button>
    </nav>
  </header>
  <main>
    <RouterView />
  </main>
</template>
