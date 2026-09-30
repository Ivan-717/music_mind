<script setup>
import { ref, onMounted } from 'vue'
import { apiAlbums } from '@/api/auth'
import { useDisplay } from '@/composables/useDisplay'
import CoverImage from '@/components/CoverImage.vue'

const { fmt } = useDisplay()

const albums = ref([])
const error = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    albums.value = await apiAlbums()      // 拦截器已经吐过 data 了
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <p v-if="loading">加载中…</p>
  <p v-else-if="error" class="err">{{ error }}</p>
  <ul v-else class="album-list">
    <li v-for="a in albums" :key="a.id">
      <CoverImage :album-id="a.id" :size="56" :alt="fmt(a.name)" />
      <RouterLink class="name" :to="`/albums/${a.id}`">{{ fmt(a.name) }}</RouterLink>
      <span class="artist">{{ fmt(a.artistNames) }}</span>
    </li>
  </ul>


</template>
