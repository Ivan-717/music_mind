<script setup>
import { ref, computed, onMounted } from 'vue'
import { apiFavoritePage, apiUnfavorite } from '@/api/favorite'
import { useDisplay } from '@/composables/useDisplay'
import { usePlayerStore } from '@/stores/player'
import CoverImage from '@/components/CoverImage.vue'

const { fmt, fmtDuration } = useDisplay()
const player = usePlayerStore()

/** 点 ▶：交给全局播放器。没有 hasPreview 的行不渲染按钮 */
function playTrack(it) {
  player.play({
    trackId: it.trackId,
    name: it.name,
    artistNames: it.artistNames,
    albumId: it.albumId
  })
}

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const loading = ref(true)
const error = ref('')
const busyId = ref(null)        // 正在取消的那一行，防重复点击

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiFavoritePage(page.value, size.value)
    items.value = data.items
    total.value = data.total
    // 边界：删掉当前页最后一条后，这一页可能已越界，回退一页重取
    if (items.value.length === 0 && page.value > 1) {
      page.value -= 1
      return load()
    }
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
}

async function remove(trackId) {
  busyId.value = trackId
  try {
    await apiUnfavorite(trackId)
    await load()
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    busyId.value = null
  }
}

function go(p) {
  if (p < 1 || p > totalPages.value || p === page.value) return
  page.value = p
  load()
}

// 后端返回 LocalDateTime，形如 2026-09-28T17:43:57
function fmtTime(t) {
  return t ? String(t).replace('T', ' ').slice(0, 16) : ''
}

onMounted(load)
</script>

<template>
  <h2>我的收藏</h2>
  <div class="rule"></div>

  <p v-if="loading">加载中…</p>
  <p v-else-if="error" class="err">{{ error }}</p>
  <p v-else-if="items.length === 0" class="empty">还没有收藏任何歌曲</p>

  <template v-else>
    <ul class="fav-list">
      <li v-for="it in items" :key="it.trackId"
          :class="{ playing: player.isCurrent(it.trackId) }">
        <CoverImage :album-id="it.albumId" :size="44" :alt="fmt(it.albumName)" />
        <div class="body">
          <div class="row">
            <span class="name">{{ fmt(it.name) }}</span>
            <span class="artist">{{ fmt(it.artistNames) }}</span>
          </div>
          <div class="row meta">
            <span class="album">{{ fmt(it.albumName) || '—' }}</span>
            <!-- 有试听的给按钮；没有的给同宽空位 —— 否则两行的列对不齐 -->
            <button
              v-if="it.hasPreview"
              class="play"
              :class="{ on: player.isCurrent(it.trackId) }"
              :title="player.isCurrent(it.trackId) && player.playing ? '暂停' : '试听 30 秒'"
              @click="playTrack(it)"
            >{{ player.isCurrent(it.trackId) && player.playing ? '❚❚' : '▶' }}</button>
            <span v-else class="play" aria-hidden="true"></span>
            <span class="dur">{{ fmtDuration(it.durationMs) }}</span>
            <span class="time">{{ fmtTime(it.favoritedAt) }}</span>
            <button :disabled="busyId === it.trackId" @click="remove(it.trackId)">
              {{ busyId === it.trackId ? '…' : '取消收藏' }}
            </button>
          </div>
        </div>
      </li>

    </ul>

    <div class="pager">
      <button :disabled="page <= 1" @click="go(page - 1)">上一页</button>
      <span>第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 首</span>
      <button :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
    </div>
  </template>
</template>
