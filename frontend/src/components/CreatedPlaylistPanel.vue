<script setup>
/**
 * 自建歌单管理面板（「我的歌单」页的「我建的」tab）。
 *
 * 【为什么单独一个组件，而不是塞进 MyPlaylistView】那边管的是**导入歌单**
 * （user_playlist_track：外部文本、match_status、分页、入库队列），
 * 这里管的是**本地曲目**（playlist_track：已经是 track id、无分页）——
 * 数据形状完全不同，用 v-if 分流会把 751 行的文件变成互相牵制的 1100 行。
 *
 * 【不做分页】自建歌单目前最长就是一次推荐的长度（≤20 首），
 * `/playlists/{id}/tracks` 也无分页。真出现长歌单再加。
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import {
  apiMyPlaylists, apiPlaylistTracks, apiRenamePlaylist,
  apiDeletePlaylist, apiRemovePlaylistTrack
} from '@/api/playlist'
import { apiFavorite, apiUnfavorite, apiFavoriteIds, apiFavoriteBatch }
  from '@/api/favorite'
import { usePlayerStore } from '@/stores/player'
import { useDisplay } from '@/composables/useDisplay'
import CoverImage from '@/components/CoverImage.vue'

const { fmt, fmtDuration } = useDisplay()
const player = usePlayerStore()
const route = useRoute()

const playlists = ref([])
const currentId = ref(null)
const tracks = ref([])
const favIds = ref(new Set())
const loading = ref(true)
const tracksLoading = ref(false)
const working = ref(false)          // 歌单级操作（收藏全部/删除）在飞
const favBusy = ref(null)
const error = ref('')
const notice = ref('')

const renaming = ref(false)         // 内联改名（不用 window.prompt —— 移动端会被拦）
const renameText = ref('')

const current = computed(
  () => playlists.value.find((p) => p.id === currentId.value) || null)

async function loadPlaylists() {
  error.value = ''
  try {
    playlists.value = await apiMyPlaylists()
    // 深链：?source=created&playlist=<id> 优先（存完歌单跳过来就是这条路），
    // 否则打开第一张
    const want = Number(route.query.playlist)
    const target = playlists.value.find((p) => p.id === want) || playlists.value[0]
    if (target) await openPlaylist(target.id)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
}

async function openPlaylist(id) {
  currentId.value = id
  renaming.value = false
  notice.value = ''
  tracksLoading.value = true
  try {
    tracks.value = await apiPlaylistTracks(id)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
    tracks.value = []
  } finally {
    tracksLoading.value = false
  }
}

function playTrack(t) {
  player.play({
    trackId: t.trackId,
    name: t.name,
    artistNames: t.artistNames,
    albumId: t.albumId
  })
}

async function toggleFav(trackId) {
  if (favBusy.value) return
  favBusy.value = trackId
  try {
    if (favIds.value.has(trackId)) {
      await apiUnfavorite(trackId)
      favIds.value.delete(trackId)
    } else {
      await apiFavorite(trackId)
      favIds.value.add(trackId)
    }
    favIds.value = new Set(favIds.value)   // 整体换新，模板 .has() 才重新求值
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    favBusy.value = null
  }
}

async function favoriteAll() {
  if (working.value || !tracks.value.length) return
  working.value = true
  notice.value = ''
  try {
    const r = await apiFavoriteBatch(tracks.value.map((t) => t.trackId))
    notice.value = `已加入收藏 ${r.changed} 首`
      + (r.unknown ? `（${r.unknown} 首库里已不存在，跳过）` : '')
    favIds.value = new Set(await apiFavoriteIds())
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    working.value = false
  }
}

async function removeTrack(t) {
  try {
    await apiRemovePlaylistTrack(currentId.value, t.trackId)
    tracks.value = tracks.value.filter((x) => x.trackId !== t.trackId)
    const p = current.value
    if (p) p.trackCount = tracks.value.length
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  }
}

function startRename() {
  renameText.value = current.value?.name || ''
  renaming.value = true
}

async function commitRename() {
  const name = renameText.value.trim()
  if (!name || !current.value) return
  try {
    await apiRenamePlaylist(current.value.id, name)
    current.value.name = name
    renaming.value = false
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  }
}

async function removePlaylist() {
  const p = current.value
  if (!p || working.value) return
  // 二次确认说清后果 —— "删歌单不动收藏、不动曲库"和导入歌单是同一条规矩
  if (!window.confirm(`删除歌单「${p.name}」？\n曲目不会从库里消失，收藏也不受影响，只是这张单子没了。`)) {
    return
  }
  working.value = true
  try {
    await apiDeletePlaylist(p.id)
    playlists.value = playlists.value.filter((x) => x.id !== p.id)
    currentId.value = null
    tracks.value = []
    if (playlists.value.length) await openPlaylist(playlists.value[0].id)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    working.value = false
  }
}

onMounted(async () => {
  try {
    favIds.value = new Set(await apiFavoriteIds())
  } catch (e) {
    /* ♡ 显示为空即可，不拦页面 */
  }
  await loadPlaylists()
})
</script>

<template>
  <p v-if="error" class="err">{{ error }}</p>
  <p v-if="loading" class="muted">加载中…</p>

  <div v-else-if="!playlists.length" class="empty">
    还没有建过歌单。去<RouterLink to="/explore">音乐探索</RouterLink>问一句，
    把推荐「存成歌单」就会出现在这里。
  </div>

  <template v-else>
    <ul class="playlist-tabs">
      <li v-for="p in playlists" :key="p.id">
        <button
          class="tab"
          :class="{ active: p.id === currentId }"
          :data-playlist-id="p.id"
          @click="openPlaylist(p.id)"
        >
          「{{ fmt(p.name) }}」
          <span v-if="p.trackCount != null" class="tab-count">{{ p.trackCount }}</span>
        </button>
      </li>
    </ul>

    <div v-if="current" class="playlist-head">
      <template v-if="renaming">
        <input
          v-model="renameText"
          class="rename-input"
          maxlength="80"
          @keyup.enter="commitRename"
          @keyup.esc="renaming = false"
        />
        <div class="playlist-actions">
          <button class="ghost" @click="commitRename">保存</button>
          <button class="ghost" @click="renaming = false">取消</button>
        </div>
      </template>
      <template v-else>
        <h3 class="section-title">
          「{{ fmt(current.name) }}」<span class="count">{{ tracks.length }} 首</span>
        </h3>
        <div class="playlist-actions">
          <button class="ghost" :disabled="working || !tracks.length" @click="favoriteAll">
            全部加入收藏
          </button>
          <button class="ghost" @click="startRename">改名</button>
          <button class="danger" :disabled="working" @click="removePlaylist">删除歌单</button>
        </div>
      </template>
    </div>

    <p v-if="notice" class="notice">{{ notice }}</p>
    <p v-if="tracksLoading" class="muted">加载曲目…</p>
    <p v-else-if="current && !tracks.length" class="muted">这张歌单是空的。</p>

    <ul v-else class="my-track-list">
      <li v-for="(t, i) in tracks" :key="t.trackId"
          :class="{ playing: player.isCurrent(t.trackId) }">
        <span class="no">{{ i + 1 }}</span>
        <CoverImage v-if="t.albumId" class="cover" :album-id="t.albumId"
                    :size="44" :alt="fmt(t.name)" />
        <span v-else class="cover placeholder"></span>

        <span class="name">{{ fmt(t.name) }}</span>
        <span class="artist">{{ fmt(t.artistNames) }}</span>
        <span class="dur">{{ fmtDuration(t.durationMs) }}</span>

        <button
          v-if="t.hasPreview"
          class="play"
          :class="{ on: player.isCurrent(t.trackId) }"
          :title="player.isCurrent(t.trackId) && player.playing ? '暂停' : '试听 30 秒'"
          @click="playTrack(t)"
        >{{ player.isCurrent(t.trackId) && player.playing ? '❚❚' : '▶' }}</button>
        <span v-else class="play" aria-hidden="true"></span>

        <button
          class="fav"
          :class="{ on: favIds.has(t.trackId) }"
          :disabled="favBusy === t.trackId"
          :title="favIds.has(t.trackId) ? '取消收藏' : '加入收藏'"
          @click="toggleFav(t.trackId)"
        >{{ favIds.has(t.trackId) ? '♥' : '♡' }}</button>

        <button class="drop" title="从歌单里移除" @click="removeTrack(t)">✕</button>
      </li>
    </ul>
  </template>
</template>
