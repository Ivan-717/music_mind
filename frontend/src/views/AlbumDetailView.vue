<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiAlbumDetail, apiAlbumTracks } from '@/api/album'
import { apiFavoriteIds, apiFavorite, apiUnfavorite } from '@/api/favorite'
import { useDisplay } from '@/composables/useDisplay'
import CoverImage from '@/components/CoverImage.vue'

const { fmt, fmtDuration } = useDisplay()

const route = useRoute()
const albumId = route.params.id

const album = ref(null)
const tracks = ref([])
const releaseId = ref(null)
const favIds = ref(new Set())      // 已收藏的 trackId 集合
const loading = ref(true)
const tracksLoading = ref(false)
const error = ref('')
const busyId = ref(null)

const currentRelease = computed(
  () => album.value?.releases.find((r) => r.releaseId === releaseId.value) || null
)

async function loadTracks() {
  tracksLoading.value = true
  error.value = ''
  try {
    tracks.value = await apiAlbumTracks(albumId, releaseId.value)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    tracksLoading.value = false
  }
}

function onReleaseChange() {
  loadTracks()
}

async function toggleFav(trackId) {
  busyId.value = trackId
  error.value = ''
  try {
    if (favIds.value.has(trackId)) {
      await apiUnfavorite(trackId)
      favIds.value.delete(trackId)
    } else {
      await apiFavorite(trackId)
      favIds.value.add(trackId)
    }
    // 整体换一个新 Set，确保模板里的 .has() 一定重新求值
    favIds.value = new Set(favIds.value)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    busyId.value = null
  }
}

onMounted(async () => {
  try {
    album.value = await apiAlbumDetail(albumId)
    // 默认选中最早发行的版本（后端已经按 release_date 升序返回）
    if (album.value.releases.length > 0) {
      releaseId.value = album.value.releases[0].releaseId
    }
    await loadTracks()
    favIds.value = new Set(await apiFavoriteIds())
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <p v-if="loading">加载中…</p>
  <p v-else-if="!album" class="err">{{ error || '专辑不存在' }}</p>

  <template v-else>
    <div class="album-head">
      <CoverImage :album-id="album.id" :size="150" :alt="fmt(album.name)" />
      <div class="album-head-text">
        <h2>{{ fmt(album.name) }}</h2>
        <p class="album-meta">
          <span>{{ fmt(album.artistNames) }}</span>
          <span v-if="album.releaseDate">{{ album.releaseDate }}</span>
          <span v-if="album.primaryType" class="tag">{{ album.primaryType }}</span>
        </p>
      </div>
    </div>


    <!-- 多个版本才显示切换器 -->
    <div v-if="album.releases.length > 1" class="release-picker">
      <label for="rel">版本</label>
      <select id="rel" v-model.number="releaseId" @change="onReleaseChange">
        <option v-for="r in album.releases" :key="r.releaseId" :value="r.releaseId">
          {{ fmt(r.title) }} · {{ r.country || '??' }} · {{ r.releaseDate || '未知' }} · {{ r.trackCount }}曲
        </option>
      </select>
    </div>
    <p v-else-if="currentRelease" class="release-single">
      {{ fmt(currentRelease.title) }} · {{ currentRelease.country || '??' }} ·
      {{ currentRelease.releaseDate || '未知' }}
    </p>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="tracksLoading">加载曲目…</p>
    <p v-else-if="tracks.length === 0" class="empty">这个版本没有曲目</p>

    <ul v-else class="track-list">
      <li v-for="t in tracks" :key="t.trackId">
        <span class="no">{{ t.trackNumber }}</span>
        <span class="name">{{ fmt(t.name) }}</span>
        <span class="artist">{{ fmt(t.artistNames) }}</span>
        <span class="dur">{{ fmtDuration(t.durationMs) }}</span>
        <button
          class="fav"
          :class="{ on: favIds.has(t.trackId) }"
          :disabled="busyId === t.trackId"
          :title="favIds.has(t.trackId) ? '取消收藏' : '收藏'"
          @click="toggleFav(t.trackId)"
        >
          {{ favIds.has(t.trackId) ? '★' : '☆' }}
        </button>
      </li>
    </ul>
  </template>
</template>
