<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiSearch } from '@/api/search'
import { apiArtistLookup } from '@/api/artist'
import { apiQueueArtist } from '@/api/ingestion'
import { apiFavoriteIds, apiFavorite, apiUnfavorite } from '@/api/favorite'
import CoverImage from '@/components/CoverImage.vue'
import { useDisplay } from '@/composables/useDisplay'
import { useCoverIndex } from '@/composables/useCoverIndex'
import { usePlayerStore } from '@/stores/player'

const { fmt, fmtDuration } = useDisplay()
const { withCover } = useCoverIndex()
const player = usePlayerStore()
const route = useRoute()

const result = ref(null)
const favIds = ref(new Set())
const loading = ref(false)
const error = ref('')

// 「补全专辑」的进行态与反馈（每个歌手都能补全，哪怕库里已有一些——
// 常听的歌手往往只缺后期的几张；已经全有的话后端如实回「没有新的可抓」）
const artistBusy = ref(null)
const artistNotice = ref('')
const artistImportId = ref(null)

async function completeArtist({ mbid, artistId, name, key }) {
  if (artistBusy.value) return
  artistBusy.value = key
  artistNotice.value = ''
  artistImportId.value = null
  try {
    const r = await apiQueueArtist({
      ...(mbid ? { mbid } : {}),
      ...(artistId ? { artistId } : {}),
      artistName: name
    })
    if (!r.found) {
      artistNotice.value = 'MusicBrainz 上没有找到可补的录音室专辑'
    } else if (!r.queued) {
      artistNotice.value = `${r.found} 张专辑都已在库里，没有新的可抓`
    } else {
      const mins = Math.ceil((r.estimateSeconds || 0) / 60)
      artistNotice.value = `已排进队列 ${r.queued} 张`
        + (r.skippedQueued ? `（${r.skippedQueued} 张已在库里或在队列里）` : '')
        + `，约 ${mins} 分钟。抓完再搜就有结果了`
    }
    artistImportId.value = r.importId || null
  } catch (e) {
    artistNotice.value = e.response?.data?.message || e.message
  } finally {
    artistBusy.value = null
  }
}
const busyId = ref(null)

/** 点 ▶：交给全局播放器。没有 hasPreview 的行不渲染按钮 */
function playTrack(t) {
  player.play({
    trackId: t.trackId,
    name: t.name,
    artistNames: t.artistNames,
    albumId: t.albumId
  })
}

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

// 【playlistHits 也要算进来】搜库里没有的歌（中文歌的多数情况）时，
// 本地三个列表全空、而第二来源有货 —— 不算它整块都不渲染，正是最需要它的时候
const hasAny = computed(() =>
  !!result.value &&
  (result.value.artists.length || result.value.albums.length
   || result.value.tracks.length || (result.value.playlistHits?.length || 0)))

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
    <div class="rule"></div>

    <!-- 补全专辑的反馈。可能"0 张"——都在库里了，如实说，别让用户以为点了没反应 -->
    <p v-if="artistNotice" class="notice">
      {{ artistNotice }}
      <RouterLink v-if="artistImportId"
                  :to="`/my-playlist?import=${artistImportId}`">去「AI 帮你找的」看进度 →</RouterLink>
    </p>
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
          <!-- 每个歌手都能补全：库里已有的专辑排队时会跳过，没有新的就如实回 -->
          <button
            class="grab"
            :disabled="!!artistBusy"
            :title="`把 ${a.name} 在 MusicBrainz 上的录音室专辑（最多 10 张）排进抓取队列`"
            @click="completeArtist({ artistId: a.id, name: a.name, key: 'a' + a.id })"
          >{{ artistBusy === 'a' + a.id ? '排队中…' : '补全专辑' }}</button>
        </li>
      </ul>
    </section>

    <!-- 第二来源：你歌单里还没入库的。库里搜不到的中文歌往往在这儿——
         「消失」变成「看得见、有状态、能试听」 -->
    <section v-if="activeTab === 'songs' && result.playlistHits?.length" class="search-section">
      <h3 class="section-title">
        你歌单里还没入库的 <span class="count">{{ result.playlistHits.length }}</span>
      </h3>
      <ul class="track-list">
        <li v-for="h in result.playlistHits" :key="h.rowId"
            :class="{ playing: player.isCurrent('n' + h.externalId) }">
          <span class="name">{{ fmt(h.title) }}</span>
          <span class="artist">{{ fmt(h.artists) }}</span>
          <span class="album">{{ fmt(h.albumName) }}</span>
          <button
            v-if="h.provider === 'netease'"
            class="play"
            :class="{ on: player.isCurrent('n' + h.externalId) }"
            :title="player.isCurrent('n' + h.externalId) && player.playing
              ? '暂停' : '播放（网易云外链，整首歌）'"
            @click="player.playNetease({ externalId: h.externalId, name: h.title,
                                          artists: h.artists, coverUrl: h.coverUrl })"
          >{{ player.isCurrent('n' + h.externalId) && player.playing ? '❚❚' : '▶' }}</button>
          <span v-else class="play" aria-hidden="true"></span>
          <span class="dur">{{ fmtDuration(h.durationMs) }}</span>
          <RouterLink class="album-link" :to="`/my-playlist?import=${h.importId}`">
            在「{{ fmt(h.playlistName) }}」里
          </RouterLink>
        </li>
      </ul>
      <p class="more-hint">这些歌 MusicBrainz 上多半没有、入不了库 —— 但可以听。</p>
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
        <li v-for="t in tracksView" :key="t.trackId"
            :class="{ playing: player.isCurrent(t.trackId) }">
          <CoverImage :album-id="t.albumId" :size="44" :alt="fmt(t.albumName)" />
          <span class="name">{{ fmt(t.name) }}</span>
          <span class="artist">{{ fmt(t.artistNames) }}</span>
          <!-- 【加这一列】原来那行只有 封面/歌名/艺人/时长 四列，
               而歌名是 flex:1 —— 短歌名会在中间留一大片空白。
               补上专辑名既填了版面，也是搜歌时真的想看的信息 -->
          <span class="album">{{ fmt(t.albumName) }}</span>
          <!-- 有试听的给按钮；没有的给同宽空位 —— 否则两行的列对不齐 -->
          <button
            v-if="t.hasPreview"
            class="play"
            :class="{ on: player.isCurrent(t.trackId) }"
            :title="player.isCurrent(t.trackId) && player.playing ? '暂停' : '试听 30 秒'"
            @click="playTrack(t)"
          >{{ player.isCurrent(t.trackId) && player.playing ? '❚❚' : '▶' }}</button>
          <span v-else class="play" aria-hidden="true"></span>
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
            <button
              class="grab"
              :disabled="!!artistBusy"
              :title="`把 ${a.name} 在 MusicBrainz 上的录音室专辑（最多 10 张）排进抓取队列`"
              @click="completeArtist({ mbid: a.mbid, name: a.name, key: 'm' + a.mbid })"
            >{{ artistBusy === 'm' + a.mbid ? '排队中…' : '补全专辑' }}</button>
          </li>
        </ul>

        <!-- 【别教用户跑命令行】原来是 `python data-pipeline/main.py "关键词"` ——
             普通用户执行不了那句，等于"此路不通"。改成产品内可走的两条路：
             去探索让 Agent 找代表专辑抓进来（先问，不自动抓），
             或者导入一张包含 TA 的歌单 -->
        <p class="lookup-tip">
          本地没有这位歌手。可以
          <RouterLink :to="{ path: '/explore', query: { q: `我想了解 ${result.keyword}` } }">
            去音乐探索问一句「我想了解 {{ result.keyword }}」</RouterLink>，
          让 Agent 查过之后把代表专辑抓进来；或者
          <RouterLink to="/import">导入一张包含 TA 的歌单</RouterLink>。
        </p>
      </div>

      <p v-else-if="lookupFailed" class="lookup-tip">
        查询 MusicBrainz 失败（可能是被限流了）。这不代表上游没有这个人——稍后再试。
      </p>

      <p v-else class="lookup-tip">MusicBrainz 上也没有名字匹配的歌手。</p>
    </div>
  </template>
</template>
