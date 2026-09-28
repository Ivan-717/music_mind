<script setup>
import { RouterView, RouterLink, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const router = useRouter()

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
      <span class="who">{{ store.user?.username || '' }}</span>
      <button @click="logout">退出</button>
    </nav>
  </header>
  <main>
    <RouterView />
  </main>
</template>
