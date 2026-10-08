<script setup>
import { ref, computed } from 'vue'
import { apiImportPlaylist } from '@/api/import'
import CoverImage from '@/components/CoverImage.vue'
import { useDisplay } from '@/composables/useDisplay'

const { fmt, providerLabel } = useDisplay()

const url = ref('')
const loading = ref(false)
const error = ref('')
const result = ref(null)

// 是否顺手加入收藏。【默认不勾】——导入是搬列表，收藏是表态。
// 不勾也不影响：歌单页里每首都能 ♡，也能勾一批批量收藏。
const alsoFavorite = ref(false)
// 记下【提交时】的值。用 result.added 反推不行——勾了但一首都没匹配上时它也是 0，
// 会和「没勾」显示成一样。
const submittedFavorite = ref(false)

const matchedItems = computed(() => (result.value?.items || []).filter((i) => i.matched))

async function submit() {
  const value = url.value.trim()
  if (!value || loading.value) return

  error.value = ''
  result.value = null
  submittedFavorite.value = alsoFavorite.value
  loading.value = true
  try {
    result.value = await apiImportPlaylist(value, alsoFavorite.value)
  } catch (e) {
    // 后端对抓取失败会返回明确原因（接口变更 / 歌单私密 / 链接不认识），
    // 原样透出来，别自己编一句「导入失败」
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <h2>导入歌单</h2>
  <div class="rule"></div>
  <p class="hint">
    粘贴网易云或 QQ 音乐的歌单链接。整份存进
    <RouterLink to="/my-playlist">我的歌单</RouterLink>，<strong>不会</strong>动你已有的收藏。
  </p>

  <div class="import-box">
    <input
      v-model="url"
      class="import-url"
      placeholder="https://music.163.com/playlist?id=..."
      @keyup.enter="submit"
    />
    <button :disabled="loading || !url.trim()" @click="submit">
      {{ loading ? '抓取中…' : '导入' }}
    </button>
  </div>

  <label class="fav-opt">
    <input v-model="alsoFavorite" type="checkbox" />
    同时把这批歌加进我的收藏
  </label>

  <p v-if="error" class="err">{{ error }}</p>

  <template v-if="result">
    <h3 class="section-title">
      「{{ fmt(result.playlistName) }}」
      <span class="count">{{ providerLabel(result.provider) }} · {{ result.parsed }} 首</span>
    </h3>

    <p class="import-summary">
      <template v-if="submittedFavorite">
        <span class="ok">✅ {{ result.added }} 首已加入收藏</span>
        <span v-if="result.alreadyFavorited" class="muted">
          （另 {{ result.alreadyFavorited }} 首本来就在收藏里）
        </span>
      </template>
      <span v-else class="muted">这次只导入歌单，没有改动收藏</span>
      <span class="gap">⬜ {{ result.parsed - result.matched }} 首本地库里还没有</span>
    </p>

    <p class="more-hint">
      <RouterLink to="/my-playlist">去「我的歌单」看这 {{ result.parsed }} 首的完整列表 →</RouterLink>
    </p>

    <template v-if="matchedItems.length">
      <h4 class="import-sub">
        {{ submittedFavorite ? '已匹配并加入收藏' : '已匹配到本地库' }}
      </h4>
      <ul class="track-list">
        <li v-for="(it, idx) in matchedItems" :key="idx">
          <CoverImage :album-id="it.localAlbumId" :size="44" :alt="fmt(it.localAlbumName)" />
          <span class="name">{{ fmt(it.trackName) }}</span>
          <span class="artist">{{ fmt(it.artist) }}</span>
          <RouterLink v-if="it.localAlbumId" class="album-link" :to="`/albums/${it.localAlbumId}`">
            {{ fmt(it.localAlbumName) }}
          </RouterLink>
          <span v-if="it.alreadyFavorited" class="state">本来就在</span>
        </li>
      </ul>
    </template>

  </template>
</template>
