<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiSearch } from '@/api/search'
import { apiArtistLookup } from '@/api/artist'
import { apiFavoriteIds, apiFavorite, apiUnfavorite } from '@/api/favorite'
import CoverImage from '@/components/CoverImage.vue'
import { useDisplay } from '@/composables/useDisplay'
import { useCoverIndex } from '@/composables/useCoverIndex'

const { fmt, fmtDuration } = useDisplay()
const { withCover } = useCoverIndex()
const route = useRoute()

const result = ref(null)
const favIds = ref(new Set())
const loading = ref(false)
const error = ref('')
const busyId = ref(null)

async function search(q) {
  if (!q) {
    result.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    result.value = await apiSearch(q)
    activeTab.value = pickDefaultTab(result.value)

    // 本地三条路全空 → 查上游。不 await：先把「没有找到」显示出来，
    // MusicBrainz 那一块慢一点到没关系，别让整个页面等它。
    if (!hasAny.value) {
      loadLookup(q)
    } else {
      lookupResults.value = []
    }
  } catch (e) {
    error.value = e.response?.data?.message || e.message
    result.value = null
  } finally {
    loading.value = false
  }
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
    // 整体换新 Set，确保模板里的 .has() 一定重新求值
    favIds.value = new Set(favIds.value)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    busyId.value = null
  }
}

// 全显示了就只写总数；被 limit 截断了才写「20 / 780」
function totalLabel(shown, total) {
  if (total == null) return shown
  return shown >= total ? `${total}` : `${shown} / ${total}`
}

/**
 * 把没有封面的往后放。
 *
 * 后端不知道封面抓取的结果（那是管道写在 frontend/public/covers/ 的），
 * 所以这一步在前端做。manifest 没加载完时 withCover 是空集，
 * 排序不生效、顺序保持原样，加载完会自动重排。
 *
 * Array.prototype.sort 是稳定的，所以同类之间保持后端给的顺序。
 */
function coverFirst(list, idOf) {
  if (!list || !list.length) return list || []
  return [...list].sort((a, b) => {
    const ca = withCover.value.has(idOf(a)) ? 0 : 1
    const cb = withCover.value.has(idOf(b)) ? 0 : 1
    return ca - cb
  })
}

const albumsView = computed(() => coverFirst(result.value?.albums, (x) => x.id))
const tracksView = computed(() => coverFirst(result.value?.tracks, (x) => x.albumId))

// 三块用 tab 切换。不分块的话 46 张专辑（每行 77px ≈ 3500px）会把歌曲挤到屏幕外，
// 而用户搜完最想干的事恰恰是收藏歌。
const activeTab = ref('songs')

// 本地一条都没有时，去 MusicBrainz 看看上游有什么（只报告，不导入）
const lookupResults = ref([])
const lookupLoading = ref(false)
const lookupFailed = ref(false)

async function loadLookup(q) {
  lookupLoading.value = true
  lookupResults.value = []
  lookupFailed.value = false
  try {
    lookupResults.value = await apiArtistLookup(q)
  } catch (e) {
    // 查上游失败不该影响搜索本身——本地结果已经在页面上了。
    // 但【必须和「查到了但没有」区分开】：MusicBrainz 限流时如果显示
    // 「上游也没有这个人」，那是在撒谎。
    lookupFailed.value = true
  } finally {
    lookupLoading.value = false
  }
}

const hasAny = computed(() =>
  !!result.value &&
  (result.value.artists.length || result.value.albums.length || result.value.tracks.length))

/**
 * 默认展示哪一块：歌曲优先，为空退到专辑，再为空退到歌手。
 * 搜索的主要目的是找歌，所以歌曲优先；搜专辑名时歌曲往往为空，自然落到专辑。
 */
function pickDefaultTab(r) {
  if (r.tracks.length) return 'songs'
  if (r.albums.length) return 'albums'
  if (r.artists.length) return 'artists'
  return 'songs'
}

onMounted(async () => {
  // 收藏状态先拿到，用户一打字结果出来就能看到 ★/☆
  try {
    favIds.value = new Set(await apiFavoriteIds())
  } catch (e) {
    /* 拿不到收藏不影响搜索，静默 */
  }
  await search(route.query.q)
})

// 导航栏那个搜索框走的是 router.push，URL 一变这里就重新搜
watch(() => route.query.q, (q) => search(q))
</script>

<template>
  <p v-if="loading">搜索中…</p>
  <p v-else-if="error" class="err">{{ error }}</p>
  <p v-else-if="!result" class="empty">在上方输入关键词开始搜索</p>

  <template v-else>
    <h2>「{{ fmt(result.keyword) }}」</h2>
    <p v-if="result.variants.length > 1" class="variants">
      已同时检索繁简两种写法：{{ result.variants.join(' / ') }}
    </p>

    <div v-if="hasAny" class="search-tabs">
      <button
        v-if="result.artists.length"
        :class="{ active: activeTab === 'artists' }"
        @click="activeTab = 'artists'"
      >
        歌手 <span class="count">{{ result.artists.length }}</span>
      </button>
      <button
        v-if="result.albums.length"
        :class="{ active: activeTab === 'albums' }"
        @click="activeTab = 'albums'"
      >
        专辑 <span class="count">{{ totalLabel(result.albums.length, result.albumTotal) }}</span>
      </button>
      <button
        v-if="result.tracks.length"
        :class="{ active: activeTab === 'songs' }"
        @click="activeTab = 'songs'"
      >
        歌曲 <span class="count">{{ totalLabel(result.tracks.length, result.trackTotal) }}</span>
      </button>
    </div>

    <section v-if="activeTab === 'artists' && result.artists.length" class="search-section">
      <ul class="artist-list">
        <li v-for="a in result.artists" :key="a.id">
          <RouterLink class="name" :to="`/artists/${a.id}`">{{ fmt(a.name) }}</RouterLink>
          <span class="disambig" v-if="a.disambiguation">{{ a.disambiguation }}</span>
        </li>
      </ul>
    </section>

    <section v-if="activeTab === 'albums' && result.albums.length" class="search-section">
      <ul class="album-list">
        <li v-for="al in albumsView" :key="al.id">
          <CoverImage :album-id="al.id" :size="56" :alt="fmt(al.name)" />
          <RouterLink class="name" :to="`/albums/${al.id}`">{{ fmt(al.name) }}</RouterLink>
          <span class="artist">{{ fmt(al.artistNames) }}</span>
        </li>
      </ul>
    </section>

    <section v-if="activeTab === 'songs' && result.tracks.length" class="search-section">
      <ul class="track-list">
        <li v-for="t in tracksView" :key="t.trackId">
          <CoverImage :album-id="t.albumId" :size="44" :alt="fmt(t.albumName)" />
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

      <!-- 被 limit 截断时的出口。
           搜索结果不做分页：363 首翻 7 页没人翻得下去，
           而且这些歌本来就全都可达（歌手页 → 专辑 → 曲目），
           只是组织方式是「按专辑」而不是「平铺」。 -->
      <p v-if="result.trackTotal > result.tracks.length" class="more-hint">
        只显示前 {{ result.tracks.length }} 首，共 {{ result.trackTotal }} 首
        <template v-if="result.artists.length === 1">
          ——
          <RouterLink :to="`/artists/${result.artists[0].id}`">
            去「{{ fmt(result.artists[0].name) }}」按专辑看全部 →
          </RouterLink>
        </template>
      </p>
    </section>

    <div v-if="!hasAny" class="no-result">
      <p class="empty">本地库里没有与「{{ fmt(result.keyword) }}」相关的内容</p>

      <p v-if="lookupLoading" class="lookup-tip">正在查 MusicBrainz…</p>

      <div v-else-if="lookupResults.length" class="lookup-box">
        <p class="lookup-title">MusicBrainz 上游有这些歌手：</p>
        <ul class="lookup-list">
          <li v-for="a in lookupResults" :key="a.mbid">
            <RouterLink v-if="a.localId" class="name" :to="`/artists/${a.localId}`">
              {{ fmt(a.name) }}
            </RouterLink>
            <span v-else class="name">{{ fmt(a.name) }}</span>

            <span class="meta">
              <span v-if="a.type" class="tag">{{ a.type }}</span>
              <span v-if="a.country" class="tag">{{ a.country }}</span>
              <span v-if="a.disambiguation" class="disambig">{{ a.disambiguation }}</span>
              <span v-if="a.aliases && a.aliases.length" class="disambig">
                又名 {{ a.aliases.slice(0, 3).join(' · ') }}
              </span>
            </span>

            <span v-if="a.localId" class="state state-ok">已导入</span>
            <span v-else class="state state-todo">本地还没有</span>
          </li>
        </ul>

        <p class="lookup-tip">
          本地没有的歌手，用管道导入（跑完再回来搜就有结果了）：
          <code>python data-pipeline/main.py "{{ result.keyword }}"</code>
        </p>
      </div>

      <p v-else-if="lookupFailed" class="lookup-tip">
        查询 MusicBrainz 失败（可能是被限流了）。这不代表上游没有这个人——稍后再试。
      </p>

      <p v-else class="lookup-tip">MusicBrainz 上也没有名字匹配的歌手。</p>
    </div>
  </template>
</template>
