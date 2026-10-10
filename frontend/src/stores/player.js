import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiTrackPreview } from '@/api/track'
import { apiReportListen } from '@/api/event'
import router from '@/router'

// 【上报节流】同一首 5 分钟内只报一次 —— 暂停/继续、反复点不该重复记。
// fire-and-forget：失败静默（api 层 catch），下一条行为会补上
const REPORT_WINDOW_MS = 5 * 60 * 1000
const lastReported = new Map()

/**
 * 来源页 → source（后端白名单见 EventService）。
 * 【只有 persona 是「推荐被采纳」的信号】—— 分析推荐质量时靠它区分
 * 「在报告里点了推荐的歌」和「自己翻专辑听到的」，不能不分。
 */
const SOURCE_BY_ROUTE = {
  persona: 'report',
  'album-detail': 'album',
  'my-playlist': 'playlist',
  search: 'search',
  favorites: 'favorite',
  'artist-detail': 'artist',
  explore: 'chat'
}

function reportListen(trackId) {
  const last = lastReported.get(trackId) || 0
  if (Date.now() - last < REPORT_WINDOW_MS) return
  lastReported.set(trackId, Date.now())
  // 从 router 单例直接读当前路由 —— 比在每个调用点传 source 少五处重复
  const name = router.currentRoute.value.name
  apiReportListen(trackId, SOURCE_BY_ROUTE[name] || 'other')
}

/**
 * 全局播放器。MiniPlayer 只是一个视图，真正的 audio 在这里 ——
 * 放 store 而不是组件里，是因为「播放」是**页面之外的状态**：
 * MiniPlayer 挂在 App.vue 上本来就切页不卸载，但哪天结构变了、
 * 组件重建一次，音乐不该跟着断。
 */
export const usePlayerStore = defineStore('player', () => {
  const track = ref(null)      // { trackId, name, artistNames, albumId?, coverUrl? }
  const playing = ref(false)
  const current = ref(0)       // 已播秒数
  const duration = ref(30)     // 预览约 30 秒；metadata 到了以实测为准
  const error = ref('')

  // 【audio 不放 DOM】new Audio() 不插入文档同样能播；
  // 插了 DOM 反而要处理「组件卸载时谁来搬它」的问题
  const audio = new Audio()
  audio.preload = 'none'

  audio.addEventListener('timeupdate', () => { current.value = audio.currentTime })
  audio.addEventListener('loadedmetadata', () => {
    if (Number.isFinite(audio.duration)) duration.value = audio.duration
  })
  audio.addEventListener('ended', () => { playing.value = false })
  audio.addEventListener('error', () => {
    const tr = track.value
    // 【网易云 VIP 歌的 404 会走到这】带 trackId 的自动退到 iTunes 的 30 秒再试一次
    // （usedFallback 防循环：备用也失败就如实报「不可用」）
    // 其它来源的错误（preview_url 过期等）不自动重查 —— 那要再打一次 iTunes，
    // 而它有 20-25/分的限速
    if (tr && !tr.usedFallback && tr.externalId && tr.trackId) {
      tr.usedFallback = true
      apiTrackPreview(tr.trackId)
        .then((r) => { audio.src = r.url; return audio.play() })
        .then(() => { error.value = ''; playing.value = true })
        .catch(() => { error.value = '试听暂时不可用'; playing.value = false })
      return
    }
    if (tr) error.value = '试听暂时不可用'
    playing.value = false
  })

  const progress = computed(() =>
    duration.value > 0 ? Math.min(1, current.value / duration.value) : 0
  )

  /**
   * 点某一首：同一首 = 播放/暂停切换；换一首 = 换源播放。
   *
   * 【音源优先级】有 externalId（网易云 id，导入歌单来的）先用外链——
   * 它给**整首歌**；失败（VIP 歌 404）onerror 里自动退 iTunes 的 30 秒。
   * 没有 externalId 的（MB 来源的歌）直接用 /tracks/{id}/preview。
   * 「当前播放中」的判定统一走 key（调用方给）。
   */
  async function play(t) {
    const key = t.key ?? String(t.trackId)
    if (track.value?.key === key) return toggle()
    if (!t.externalId && !t.trackId) {
      track.value = { ...t, key }
      error.value = '试听暂时不可用'
      return
    }

    // 【先摆上 track 再请求】播放条立刻出现（显示「加载中」的样子），
    // 而不是点完等 200ms 没反应
    track.value = { ...t, key, usedFallback: false }
    current.value = 0
    duration.value = 30
    error.value = ''
    try {
      const url = t.externalId
        ? `https://music.163.com/song/media/outer/url?id=${t.externalId}.mp3`
        : (await apiTrackPreview(t.trackId)).url
      audio.src = url
      await audio.play()
      playing.value = true
      // 未入库的歌不上报：play_history.track_id 有外键，null 会炸
      if (t.trackId) reportListen(t.trackId)
    } catch (e) {
      error.value = '试听暂时不可用'
      playing.value = false
    }
  }

  /**
   * 带网易云 id 的歌（导入歌单来的，入库与否都算）：整曲优先。
   * 已对齐的传 trackId 当兜底（VIP 歌 404 时自动退 iTunes 30 秒）；
   * 未入库的没有 trackId，404 就如实说不可用。
   * 入参：{ externalId, trackId?, name, artists, coverUrl }
   */
  function playNetease(row) {
    return play({
      key: row.externalId ? 'n' + row.externalId : String(row.trackId),
      externalId: row.externalId,
      trackId: row.trackId,
      name: row.name,
      artistNames: row.artists,
      coverUrl: row.coverUrl
    })
  }

  /**
   * 跳到整段的比例位置（进度条点击）。时长还没加载出来（metadata 未到）时忽略——
   * 这时 audio.duration 是 NaN，设 currentTime 会抛。
   */
  function seekTo(ratio) {
    if (!track.value || !Number.isFinite(audio.duration) || audio.duration <= 0) return
    const r = Math.min(1, Math.max(0, ratio))
    audio.currentTime = r * audio.duration
    current.value = audio.currentTime     // 立即反映；timeupdate 稍后才回来
  }

  function toggle() {
    if (!track.value || error.value) return
    if (playing.value) {
      audio.pause()
      playing.value = false
    } else {
      audio.play().then(() => { playing.value = true })
        .catch(() => { error.value = '试听暂时不可用' })
    }
  }

  function close() {
    audio.pause()
    // 移除 src 释放这次流 —— 只 pause 的话音频流还挂着
    audio.removeAttribute('src')
    track.value = null
    playing.value = false
    current.value = 0
    error.value = ''
  }

  /** 当前行是不是这一首（列表里高亮播放行用） */
  /** 当前行是不是这一首。入参可以是 trackId（数字）或未对齐歌的 key（'n'+externalId） */
  const isCurrent = (id) => track.value != null && track.value.key === String(id)

  return { track, playing, current, duration, error, progress,
           play, playNetease, toggle, seekTo, close, isCurrent }
})
