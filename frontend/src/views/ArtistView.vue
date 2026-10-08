<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiArtistDetail } from '@/api/artist'
import CoverImage from '@/components/CoverImage.vue'
import { useDisplay } from '@/composables/useDisplay'

const { fmt } = useDisplay()
const route = useRoute()
const router = useRouter()

const artist = ref(null)
const loading = ref(true)
const error = ref('')

/**
 * 和专辑详情同一个模式：回「来的地方」（主要是搜索结果），
 * 直接打开链接（没有上一页）时兜底回专辑列表
 */
function goBack() {
  if (window.history.state?.back) router.back()
  else router.replace('/albums')
}

async function load(id) {
  loading.value = true
  error.value = ''
  artist.value = null
  try {
    artist.value = await apiArtistDetail(id)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
}

onMounted(() => load(route.params.id))

// 同一条路由换参数时 Vue 会复用组件实例，onMounted 不会再跑
watch(() => route.params.id, (id) => {
  if (id) load(id)
})
</script>

<template>
  <p v-if="loading">加载中…</p>
  <p v-else-if="!artist" class="err">{{ error || '歌手不存在' }}</p>

  <template v-else>
    <button class="back-link" @click="goBack">← 返回</button>

    <div class="artist-head">
      <h2>{{ fmt(artist.name) }}</h2>

      <p class="artist-meta">
        <span v-if="artist.albumCount">{{ artist.albumCount }} 张专辑</span>
        <span v-if="artist.trackCount">{{ artist.trackCount }} 首曲目</span>
      </p>

      <p v-if="artist.disambiguation" class="disambig">{{ artist.disambiguation }}</p>

      <p v-if="artist.aliases.length" class="alias-line">
        <span class="label">又名</span>
        <span v-for="(a, i) in artist.aliases" :key="a">
          <span>{{ a }}</span><span v-if="i < artist.aliases.length - 1"> · </span>
        </span>
      </p>

      <p v-if="artist.genres.length" class="genre-line">
        <span class="label">流派</span>
        <span v-for="g in artist.genres" :key="g" class="tag">{{ g }}</span>
      </p>
    </div>

    <h3 class="section-title">专辑 <span class="count">{{ artist.albums.length }}</span></h3>

    <p v-if="!artist.albums.length" class="empty">这位歌手在库里还没有专辑</p>

    <ul v-else class="album-list">
      <li v-for="a in artist.albums" :key="a.id">
        <CoverImage :album-id="a.id" :size="56" :alt="fmt(a.name)" />
        <RouterLink class="name" :to="`/albums/${a.id}`">{{ fmt(a.name) }}</RouterLink>
        <span class="meta">
          <span v-if="a.releaseDate" class="date">{{ a.releaseDate }}</span>
          <span v-if="a.primaryType" class="tag">{{ a.primaryType }}</span>
          <span v-if="a.trackCount" class="tracks">{{ a.trackCount }} 曲</span>
        </span>
      </li>
    </ul>
  </template>
</template>
