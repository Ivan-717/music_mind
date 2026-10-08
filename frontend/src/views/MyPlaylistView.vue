<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import {
  apiListImports, apiImportTracks, apiDeleteImport,
  apiRemoveImportTrack, apiFavoriteAll
} from '@/api/import'
import { apiFavoriteBatch, apiUnfavoriteBatch } from '@/api/favorite'
import {
  apiQueueTracks, apiQueueAll, apiIngestionStatus,
  apiStopIngestion, apiResumeIngestion
} from '@/api/ingestion'
import { useDisplay } from '@/composables/useDisplay'
import { usePlayerStore } from '@/stores/player'

const { fmt, fmtDuration, providerLabel } = useDisplay()
const player = usePlayerStore()

/** 点 ▶：交给全局播放器。曲目用的是对齐后的本地 id（matchedTrackId），
 *  未对齐的行没有 id、也没有按钮（v-if="t.hasPreview" 挡着） */
function playTrack(t) {
  player.play({
    trackId: t.matchedTrackId,
    name: t.title,
    artistNames: t.artists,
    coverUrl: t.coverUrl
  })
}

const PAGE_SIZE = 50

const playlists = ref([])
const currentId = ref(null)
const pageData = ref(null)

/**
 * 曲目列表的筛选：all / matched / unmatched。
 * 【筛在服务端】——分页和总数都是服务端算的，前端只筛当页会让页码骗人。
 */
const filter = ref('all')
const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'matched', label: '已收录' },
  { key: 'unmatched', label: '未收录' }
]

const loadingList = ref(false)
const loadingTracks = ref(false)
const working = ref(false)          // 批量操作进行中，锁住所有按钮
const error = ref('')
const notice = ref('')

/** 勾选的行 id（user_playlist_track 的 id）。Set 在 Vue 3 里是响应式的 */
const selected = ref(new Set())

// ============================================================
// 按需入库（③）
//
// 队列在服务端跑，这边只负责「点一下」和「看进度」。轮询到没有活动任务就停表。
// ============================================================

/** 服务端队列状态。null = 还没查到 */
const ingestion = ref(null)
const ingestBusy = ref(false)
const ingestError = ref('')

let pollTimer = null
/** 轮询间隔。一次入库 6~7 秒，3 秒的粒度足够，也不会把接口刷爆 */
const POLL_MS = 3000

// 【轮询失败不能一次就停】见 refreshStatus 的说明。
// 5 次 × 3 秒 = 15 秒：够跨过一次网络抖动，又不至于对着挂掉的后端一直打
const POLL_MAX_FAILURES = 5
let pollFailures = 0
const pollStopped = ref(false)   // 放弃轮询了，等用户点「重新连接」

/** 队列里还活着吗。没有活动任务就该停表，别让页面开着一直空转 */
const hasActiveJob = computed(() =>
  !!ingestion.value &&
  (ingestion.value.currentJobId !== null || ingestion.value.queueCount > 0)
)

/** 失败的任务。NOT_FOUND 也算——用户需要知道哪几首上游确实没有 */
const failedJobs = computed(() =>
  (ingestion.value?.recentJobs || [])
    .filter((j) => j.status === 'FAILED' || j.status === 'NOT_FOUND')
    .slice(0, 5)
)

/** 这一行是不是正在被抓 */
function isIngesting(rowId) {
  return !!ingestion.value?.activeTrackRowIds?.includes(rowId)
}

const totalPages = computed(() =>
  pageData.value ? Math.max(1, Math.ceil(pageData.value.total / pageData.value.size)) : 1
)
const current = computed(() =>
  playlists.value.find((p) => p.id === currentId.value) || null
)

const items = computed(() => pageData.value?.items || [])

/**
 * 全量总数。
 *
 * 【不能再用 pageData.total】它现在跟着筛选走。三个状态计数始终是全量的，
 * 加起来就是全量总数——用它，筛选标签上的数字才不会随筛选变来变去。
 */
const globalTotal = computed(() => {
  const d = pageData.value
  return d ? d.matchedCount + d.pendingCount + d.unresolvedCount : 0
})

function filterCount(key) {
  const d = pageData.value
  if (!d) return 0
  if (key === 'matched') return d.matchedCount
  if (key === 'unmatched') return d.pendingCount + d.unresolvedCount
  return globalTotal.value
}

/** 没对齐的歌收藏不了（本地 track 表里没这条记录），所以勾选框对它们是禁用的 */
const selectableItems = computed(() => items.value.filter((t) => t.matchedTrackId))
const selectedItems = computed(() => items.value.filter((t) => selected.value.has(t.id)))
const toAdd = computed(() => selectedItems.value.filter((t) => !t.favorited))
const toRemove = computed(() => selectedItems.value.filter((t) => t.favorited))
const allSelected = computed(() =>
  selectableItems.value.length > 0 && selected.value.size === selectableItems.value.length
)

/**
 * 平台封面地址。网易云的可以用 ?param=WxH 拿小图（实测 13.5KB vs 180KB），
 * QQ 音乐给的就是 300x300 的成品图，加参数反而可能 404，所以只认网易云的域名。
 */
function coverSrc(url, size = 100) {
  if (!url) return ''
  if (url.includes('music.126.net')) {
    const sep = url.includes('?') ? '&' : '?'
    return `${url}${sep}param=${size}y${size}`
  }
  return url
}

const STATUS_TEXT = { MATCHED: '已收录', PENDING: '识别中', UNRESOLVED: '未收录' }
const statusLabel = (s) => STATUS_TEXT[s] || '识别中'

function setSelected(next) {
  selected.value = next          // 整体替换，最保险的触发方式
}

function toggleOne(t) {
  if (!t.matchedTrackId) return
  const next = new Set(selected.value)
  next.has(t.id) ? next.delete(t.id) : next.add(t.id)
  setSelected(next)
}

function toggleAll() {
  setSelected(allSelected.value ? new Set() : new Set(selectableItems.value.map((t) => t.id)))
}

async function loadPlaylists() {
  loadingList.value = true
  error.value = ''
  try {
    playlists.value = await apiListImports()
    const stillThere = playlists.value.some((p) => p.id === currentId.value)
    if (!stillThere) {
      currentId.value = playlists.value.length ? playlists.value[0].id : null
      pageData.value = null
    }
    if (currentId.value) await loadTracks(currentId.value, 1)
    else pageData.value = null
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    loadingList.value = false
  }
}

async function loadTracks(id, page = 1) {
  if (!id) return
  loadingTracks.value = true
  error.value = ''
  try {
    const data = await apiImportTracks(id, page, PAGE_SIZE, filter.value)
    // 边界：入库把当前页的歌都收进去了，「未收录」这一页可能已经空掉，回退一页
    // （回退会再走一次 loadTracks，所以这里直接 return）
    if (data.items.length === 0 && page > 1) {
      return loadTracks(id, page - 1)
    }
    pageData.value = data
    setSelected(new Set())        // 换页/刷新后旧勾选已无意义
  } catch (e) {
    error.value = e.response?.data?.message || e.message
    pageData.value = null
  } finally {
    loadingTracks.value = false
  }
}

function selectPlaylist(id) {
  if (id === currentId.value || loadingTracks.value) return
  currentId.value = id
  pageData.value = null
  loadTracks(id, 1)
}

/** 换筛选。回第一页——第 3 页在另一个筛选下是没有意义的 */
function setFilter(key) {
  if (key === filter.value || loadingTracks.value) return
  filter.value = key
  loadTracks(currentId.value, 1)
}

function goPage(p) {
  if (p < 1 || p > totalPages.value || p === pageData.value?.page) return
  loadTracks(currentId.value, p)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

/** 批量收藏 / 取消。remove=true 是取消 */
async function batchFavorite(remove) {
  const targets = remove ? toRemove.value : toAdd.value
  if (!targets.length || working.value) return

  const trackIds = targets.map((t) => t.matchedTrackId)
  working.value = true
  error.value = ''
  notice.value = ''
  try {
    const r = remove
      ? await apiUnfavoriteBatch(trackIds)
      : await apiFavoriteBatch(trackIds)
    targets.forEach((t) => { t.favorited = !remove })
    // 不在当前页但被勾选的不会有——勾选只发生在当前页，所以这里够用
    setSelected(new Set())
    notice.value = `${remove ? '取消收藏' : '加入收藏'} ${r.changed} 首`
      + (r.unknown ? `（${r.unknown} 首本地库里没有，已跳过）` : '')
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    working.value = false
  }
}

/** 单首 ♡。等接口返回再改状态——乐观更新在失败时会让界面骗人 */
async function toggleFavorite(t) {
  if (!t.matchedTrackId || working.value) return
  working.value = true
  error.value = ''
  try {
    if (t.favorited) {
      await apiUnfavoriteBatch([t.matchedTrackId])
      t.favorited = false
    } else {
      await apiFavoriteBatch([t.matchedTrackId])
      t.favorited = true
    }
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    working.value = false
  }
}

async function favoriteAll() {
  if (!currentId.value || working.value) return
  working.value = true
  notice.value = ''
  error.value = ''
  try {
    const r = await apiFavoriteAll(currentId.value)
    notice.value = `加入收藏 ${r.added} 首`
      + (r.alreadyFavorited ? `，${r.alreadyFavorited} 首本来就在` : '')
      + (r.notMatched ? `，${r.notMatched} 首还没识别，收藏不了` : '')
    await loadTracks(currentId.value, pageData.value?.page || 1)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    working.value = false
  }
}

async function removeTrack(t) {
  if (working.value) return
  // 剔除是不可逆的（重新导入也不会回来），问一句
  if (!window.confirm(`把「${fmt(t.title)}」从歌单里剔除？\n收藏不受影响，但重新导入也不会再出现。`)) {
    return
  }
  working.value = true
  error.value = ''
  try {
    await apiRemoveImportTrack(currentId.value, t.id)
    await loadTracks(currentId.value, pageData.value.page)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    working.value = false
  }
}

async function deletePlaylist() {
  const name = fmt(current.value?.playlistName) || '这个歌单'
  if (!window.confirm(`删除歌单「${name}」？\n\n歌单和里面的曲目记录都会被删掉。\n收藏里的歌不受影响，重新导入一次就能把歌单拿回来。`)) {
    return
  }
  working.value = true
  error.value = ''
  try {
    await apiDeleteImport(currentId.value)
    currentId.value = null
    pageData.value = null
    await loadPlaylists()
    notice.value = '歌单已删除'
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    working.value = false
  }
}

function hideBroken(e) {
  e.target.style.visibility = 'hidden'
}

// ============================================================
// 按需入库：轮询
// ============================================================

async function refreshStatus() {
  try {
    ingestion.value = await apiIngestionStatus()
    pollFailures = 0
    return true
  } catch (e) {
    // 【一次抖动不能停表】原来这里直接 stopPoll() —— 而 ingestion 还停在
    // 最后一次成功的样子，hasActiveJob 恒真，于是那一行永远显示「抓取中」，
    // ♡ 和入库按钮永久禁用，没有报错、也没有恢复入口，只能刷新页面。
    //
    // 改成连续失败才停。停下来时必须让用户看得见（见模板里的 pollStopped 块）
    pollFailures += 1
    if (pollFailures >= POLL_MAX_FAILURES) {
      stopPoll()
      pollStopped.value = true
    }
    return false
  }
}

/**
 * 静默重取当前页。
 *
 * 【不能复用 loadTracks】它会 setSelected(new Set()) 把勾选清空——
 * 用户勾了十首正在等批量收藏，后台抓完一首就把勾选全清了，这不能接受。
 * 这里只换 pageData，勾选集合是按行 id 存的，不受影响。
 */
async function refreshPageSilently() {
  const id = currentId.value
  if (!id || !pageData.value) return
  try {
    const fresh = await apiImportTracks(id, pageData.value.page, PAGE_SIZE, filter.value)
    // 翻页竞态：请求飞在半路时用户点了翻页，这一份就过期了
    if (currentId.value === id && pageData.value?.page === fresh.page) {
      // 入库把这一页的歌全收进去了（「未收录」筛尤其容易），退一页。
      // 这里只能走 loadTracks（会清勾选）——页都空了，勾选本来也没意义了
      if (fresh.items.length === 0 && fresh.page > 1) {
        await loadTracks(id, fresh.page - 1)
        return
      }
      pageData.value = fresh
    }
  } catch (e) {
    /* 静默：后台刷新失败就等下一轮，不要弹错 */
  }
}

async function tick() {
  const before = JSON.stringify(ingestion.value?.activeTrackRowIds || [])
  const ok = await refreshStatus()

  const after = JSON.stringify(ingestion.value?.activeTrackRowIds || [])
  // 有行刚从「抓取中」变成别的状态 → 重取当前页，让 ♡ 和状态文字跟上
  if (before !== after) {
    await refreshPageSilently()
  }

  // 【只有真拿到过状态，才有资格判断「队列空了」】没查到就停表的话，
  // 排队后那一次失败会让进度永远不出现 —— 用户以为点了没反应。
  // 连续失败那条路走 refreshStatus 里的计数，不在这儿停
  if (ok && !hasActiveJob.value) {
    stopPoll()
  }
}

function startPoll() {
  if (pollTimer) return
  pollFailures = 0
  pollStopped.value = false
  tick()
  pollTimer = setInterval(tick, POLL_MS)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ============================================================
// 按需入库：操作
// ============================================================

function ingestSummary(r) {
  let text = `已排队 ${r.queued} 首`
  if (r.skippedAlreadyMatched) text += `，${r.skippedAlreadyMatched} 首刚入库就能对上（已直接收录）`
  if (r.skippedQueued) text += `，${r.skippedQueued} 首已在队列里`
  if (r.skippedInvalid) text += `，${r.skippedInvalid} 首信息不全跳过`
  return text
}

/** 逐首入库 */
async function ingestOne(t) {
  if (working.value || ingestBusy.value || isIngesting(t.id)) return
  ingestBusy.value = true
  ingestError.value = ''
  notice.value = ''
  try {
    const r = await apiQueueTracks([t.id])
    notice.value = ingestSummary(r)
    await refreshStatus()
    // 【排队那一刻就对上的，必须自己重取一次】
    // 这种歌根本不会产生任务（专辑已经被别人抓过了），后端在排队时就顺手把
    // 对齐结果写回了库。光等轮询永远等不到刷新——页面上那一行会一直显示「未收录」，
    // 用户以为点了没反应
    if (r.skippedAlreadyMatched > 0) {
      await refreshPageSilently()
    }
    startPoll()
  } catch (e) {
    ingestError.value = e.response?.data?.message || e.message
  } finally {
    ingestBusy.value = false
  }
}

/** 整单入库：把还没收录的一起排上 */
async function ingestAll() {
  const count = pageData.value?.unresolvedCount || 0
  if (!count || working.value || ingestBusy.value) return

  // 说成「最多」而不是「预计」：同一张专辑里有多首时只抓一次，
  // 已经被别的任务解决掉的更是几十毫秒，实际几乎总是比这个数快
  const minutes = Math.ceil((count * 4) / 60)
  const ok = window.confirm(
    `把还没收录的 ${count} 首排队入库？\n\n` +
    `会去 MusicBrainz 逐首找专辑再整张抓下来，最多约 ${minutes} 分钟。\n` +
    `同一张专辑只抓一次（专辑里别的歌会顺带收录）。\n\n` +
    `在后台排队跑，可以随时停止，关掉这个页面也不会中断。`
  )
  if (!ok) return

  ingestBusy.value = true
  ingestError.value = ''
  notice.value = ''
  try {
    const r = await apiQueueAll(currentId.value)
    notice.value = ingestSummary(r)
    await refreshStatus()
    // 同上：有歌在排队那一刻就对上了，得自己重取一次才看得到
    if (r.skippedAlreadyMatched > 0) {
      await refreshPageSilently()
    }
    startPoll()
  } catch (e) {
    ingestError.value = e.response?.data?.message || e.message
  } finally {
    ingestBusy.value = false
  }
}

async function stopIngest() {
  ingestBusy.value = true
  try {
    ingestion.value = await apiStopIngestion()
  } catch (e) {
    ingestError.value = e.response?.data?.message || e.message
  } finally {
    ingestBusy.value = false
  }
}

async function resumeIngest() {
  ingestBusy.value = true
  try {
    ingestion.value = await apiResumeIngestion()
    startPoll()
  } catch (e) {
    ingestError.value = e.response?.data?.message || e.message
  } finally {
    ingestBusy.value = false
  }
}

onMounted(async () => {
  await loadPlaylists()
  // 队列是全局共享的：别人排的队、或者上次没跑完的，刷新页面后也要能看到进度。
  // 有活动任务就开始轮询，没有的话 refreshStatus 之后 tick 会自己停表
  startPoll()
})

onUnmounted(stopPoll)

// 切换歌单时自动加载（selectPlaylist 已经加载了，这里兜住 currentId 被别处改的情况）
watch(currentId, (id) => {
  if (id && !pageData.value) loadTracks(id, 1)
})
</script>

<template>
  <h2>我的歌单</h2>
  <div class="rule"></div>

  <p v-if="error" class="err">{{ error }}</p>
  <p v-if="ingestError" class="err">{{ ingestError }}</p>
  <p v-if="notice" class="notice">{{ notice }}</p>

  <p v-if="loadingList" class="muted">加载中…</p>

  <p v-else-if="!playlists.length" class="hint">
    还没有导入过歌单。去
    <RouterLink to="/import">导入歌单</RouterLink>
    粘一个网易云或 QQ 音乐的链接。
  </p>

  <template v-else>
    <div v-if="playlists.length > 1" class="playlist-tabs">
      <button
        v-for="p in playlists"
        :key="p.id"
        class="tab"
        :class="{ active: p.id === currentId }"
        @click="selectPlaylist(p.id)"
      >
        {{ fmt(p.playlistName) }}
        <span class="tab-count">{{ p.trackCount }}</span>
      </button>
    </div>

    <div class="playlist-head">
      <h3 class="section-title">
        「{{ fmt(current?.playlistName) }}」
        <span class="count">{{ providerLabel(current?.provider) }}</span>
      </h3>
      <div class="playlist-actions">
        <button
          v-if="pageData && pageData.unresolvedCount > 0"
          class="ghost"
          :disabled="working || ingestBusy"
          @click="ingestAll"
        >批量入库 ({{ pageData.unresolvedCount }})</button>
        <button class="ghost" :disabled="working" @click="favoriteAll">全部加入收藏</button>
        <button class="danger" :disabled="working" @click="deletePlaylist">删除歌单</button>
      </div>
    </div>

    <!-- 和服务器失去联系。**必须单独一块** —— 下面那块面板的判断依赖
         ingestion，而这条恰恰是「ingestion 已经不可信了」的时候。
         不说的话页面看起来一切正常，只是永远不更新 -->
    <div v-if="pollStopped" class="ingest-panel">
      <div class="ingest-row">
        <span class="ingest-dot paused"></span>
        <span class="grow err">
          和服务器失去联系了（连着 {{ POLL_MAX_FAILURES }} 次没连上）。
          进度可能不是最新的，但抓取在后台照常跑。
        </span>
        <button class="ghost sm" @click="startPoll">重新连接</button>
      </div>
    </div>

    <!-- 入库进度。队列是全局共享的，所以别人排的队你也会看到 -->
    <div v-if="ingestion && (hasActiveJob || failedJobs.length)" class="ingest-panel">
      <div class="ingest-row">
        <span class="ingest-dot" :class="{ paused: ingestion.paused }"></span>
        <span v-if="ingestion.currentJobId" class="ingest-now">
          {{ ingestion.currentLabel }}
        </span>
        <span v-else-if="hasActiveJob" class="muted">准备中…</span>
        <span v-else class="muted">队列已跑完</span>

        <span v-if="ingestion.queueCount" class="muted">· 还剩 {{ ingestion.queueCount }} 首</span>
        <span v-if="ingestion.queueCount" class="muted">
          · 最多 {{ Math.ceil((ingestion.queueCount * 4) / 60) }} 分钟
        </span>

        <span class="grow"></span>
        <button v-if="hasActiveJob && !ingestion.paused"
                class="ghost sm" :disabled="ingestBusy" @click="stopIngest">停止</button>
        <button v-else-if="hasActiveJob && ingestion.paused"
                class="ghost sm" :disabled="ingestBusy" @click="resumeIngest">继续</button>
      </div>

      <p v-if="ingestion.paused && hasActiveJob" class="muted ingest-note">
        已暂停。正在抓的这首会跑完，后面的排队不动。关掉页面不影响。
      </p>

      <p v-if="failedJobs.length" class="muted ingest-note">
        最近没抓到的（MusicBrainz 上确实没有的居多）：
      </p>
      <ul v-if="failedJobs.length" class="ingest-fails">
        <li v-for="j in failedJobs" :key="j.id">
          <span class="name">{{ fmt(j.title) }}</span>
          <span class="artist">{{ fmt(j.artistName) }}</span>
          <span class="why">{{ j.status === 'NOT_FOUND' ? 'MusicBrainz 上没有' : j.errorMessage }}</span>
        </li>
      </ul>
    </div>

    <!-- 筛选 + 计数二合一。三个数字始终是全量的，不随当前筛选变 -->
    <div v-if="pageData" class="status-tabs">
      <button
        v-for="f in FILTERS"
        :key="f.key"
        :class="{ active: filter === f.key }"
        @click="setFilter(f.key)"
      >
        {{ f.label }} <span class="count">{{ filterCount(f.key) }}</span>
      </button>
      <span v-if="pageData.pendingCount" class="muted tab-note">
        识别中 {{ pageData.pendingCount }} 首（重新导入一次就能对上）
      </span>
    </div>

    <p v-if="loadingTracks" class="muted">加载曲目…</p>

    <template v-else-if="pageData">
      <!-- 勾选操作条。有勾选才出现，不占没勾选时的视觉空间 -->
      <div class="select-bar">
        <label class="pick-all">
          <input
            type="checkbox"
            :checked="allSelected"
            :disabled="!selectableItems.length"
            @change="toggleAll"
          />
          全选本页（{{ selectableItems.length }} 首可收藏）
        </label>
        <span v-if="selected.size" class="pick-count">已选 {{ selected.size }} 首</span>
        <button
          v-if="toAdd.length"
          class="ghost sm"
          :disabled="working"
          @click="batchFavorite(false)"
        >加入收藏 ({{ toAdd.length }})</button>
        <button
          v-if="toRemove.length"
          class="ghost sm"
          :disabled="working"
          @click="batchFavorite(true)"
        >取消收藏 ({{ toRemove.length }})</button>
      </div>

      <ul class="my-track-list">
        <li
          v-for="t in items"
          :key="t.id"
          :class="{ picked: selected.has(t.id), playing: player.isCurrent(t.matchedTrackId) }"
        >
          <input
            class="pick"
            type="checkbox"
            :checked="selected.has(t.id)"
            :disabled="!t.matchedTrackId"
            :title="t.matchedTrackId ? '' : '还没进本地库，收藏不了'"
            @change="toggleOne(t)"
          />
          <span class="no">{{ t.position }}</span>
          <img
            v-if="t.coverUrl"
            class="cover"
            :src="coverSrc(t.coverUrl)"
            width="44" height="44" loading="lazy" alt=""
            @error="hideBroken"
          />
          <span v-else class="cover placeholder"></span>

          <span class="name">{{ fmt(t.title) }}</span>
          <span class="artist">{{ fmt(t.artists) }}</span>
          <span class="album">{{ fmt(t.albumName) }}</span>
          <!-- 没有试听源的曲目【不给按钮】——给一个播不了的按钮比不给更糟 -->
          <button
            v-if="t.hasPreview"
            class="play"
            :class="{ on: player.isCurrent(t.matchedTrackId) }"
            :title="player.isCurrent(t.matchedTrackId) && player.playing ? '暂停' : '试听 30 秒'"
            @click="playTrack(t)"
          >{{ player.isCurrent(t.matchedTrackId) && player.playing ? '❚❚' : '▶' }}</button>
          <!-- 没试听的给同宽空位 —— 否则两行的列对不齐 -->
          <span v-else class="play" aria-hidden="true"></span>
          <span class="dur">{{ fmtDuration(t.durationMs) }}</span>
          <span class="state" :class="t.matchStatus.toLowerCase()">
            {{ statusLabel(t.matchStatus) }}
          </span>

          <!-- 还没进本地库的才需要抓。抓完 status 变成「已收录」，这个按钮自己消失。
               已对齐的行给一个同宽空位 —— 否则「有时长列，有时没有」的两种行
               连后面的 ♡ / ✕ 都对不齐（用户点名的问题，和 ▶ 同一类） -->
          <button
            v-if="!t.matchedTrackId"
            class="ingest"
            :class="{ busy: isIngesting(t.id) }"
            :disabled="working || ingestBusy || isIngesting(t.id)"
            :title="isIngesting(t.id)
              ? '正在抓这张专辑，同一张专辑只会抓一次'
              : '去 MusicBrainz 找这张专辑并整张抓下来（约 7 秒）'"
            @click="ingestOne(t)"
          >{{ isIngesting(t.id) ? '抓取中' : '入库' }}</button>
          <span v-else class="ingest-ghost" aria-hidden="true"></span>

          <button
            class="fav"
            :class="{ on: t.favorited }"
            :disabled="!t.matchedTrackId || working"
            :title="t.matchedTrackId
              ? (t.favorited ? '取消收藏' : '加入收藏')
              : '还没进本地库，暂时收藏不了'"
            @click="toggleFavorite(t)"
          >{{ t.favorited ? '♥' : '♡' }}</button>

          <button
            class="drop"
            :disabled="working"
            title="从歌单里剔除"
            @click="removeTrack(t)"
          >✕</button>
        </li>
      </ul>

      <p v-if="!items.length" class="muted">这个歌单里没有曲目。</p>

      <div v-if="totalPages > 1" class="pager">
        <button :disabled="pageData.page <= 1" @click="goPage(pageData.page - 1)">上一页</button>
        <span class="page-info">第 {{ pageData.page }} / {{ totalPages }} 页</span>
        <button :disabled="pageData.page >= totalPages" @click="goPage(pageData.page + 1)">
          下一页
        </button>
      </div>
    </template>
  </template>
</template>
