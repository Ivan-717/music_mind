<script setup>
import { ref, computed, onMounted } from 'vue'
import { apiFavoritePage, apiUnfavorite } from '@/api/favorite'

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

function fmtDuration(ms) {
  if (ms == null) return '--:--'
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// 后端返回 LocalDateTime，形如 2026-09-28T17:43:57
function fmtTime(t) {
  return t ? String(t).replace('T', ' ').slice(0, 16) : ''
}

onMounted(load)
</script>

<template>
  <h2>我的收藏</h2>

  <p v-if="loading">加载中…</p>
  <p v-else-if="error" class="err">{{ error }}</p>
  <p v-else-if="items.length === 0" class="empty">还没有收藏任何歌曲</p>

  <template v-else>
    <ul class="fav-list">
      <li v-for="it in items" :key="it.trackId">
        <div class="row">
          <span class="name">{{ it.name }}</span>
          <span class="artist">{{ it.artistNames }}</span>
        </div>
        <div class="row meta">
          <span class="album">{{ it.albumName || '—' }}</span>
          <span class="dur">{{ fmtDuration(it.durationMs) }}</span>
          <span class="time">{{ fmtTime(it.favoritedAt) }}</span>
          <button :disabled="busyId === it.trackId" @click="remove(it.trackId)">
            {{ busyId === it.trackId ? '…' : '取消收藏' }}
          </button>
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
