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
    // 年份在这里切一次，不在模板里对同一行调两遍 slice
    albums.value = (await apiAlbums()).map((a) => ({   // 拦截器已经吐过 data 了
      ...a,
      year: a.releaseDate ? String(a.releaseDate).slice(0, 4) : ''
    }))
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="album-grid-head">
    <h2>专辑</h2>
    <span v-if="!loading && !error" class="muted">{{ albums.length }} 张</span>
  </div>

  <p v-if="loading" class="muted">加载中…</p>
  <p v-else-if="error" class="err">{{ error }}</p>

  <!--
    网格而不是列表：封面是这一页唯一有信息量的东西，列表里的 56px 缩略图
    等于把 471 张封面压成一列小方块，既看不清也翻不完。
  -->
  <ul v-else class="album-grid">
    <li v-for="a in albums" :key="a.id">
      <RouterLink class="card" :to="`/albums/${a.id}`">
        <CoverImage :album-id="a.id" fill :alt="fmt(a.name)" />
        <span class="card-name">{{ fmt(a.name) }}</span>
        <span class="card-sub">
          {{ fmt(a.artistNames) }}<template v-if="a.year"> · {{ a.year }}</template>
        </span>
      </RouterLink>
    </li>
  </ul>
</template>
