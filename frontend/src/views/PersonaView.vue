<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  apiRequestReport, apiAsk, apiRunStatus,
  apiMyReports, apiReportDetail, apiClaimType,
  apiAgentStatus, apiStopAgent, apiResumeAgent
} from '@/api/persona'
import { apiListImports } from '@/api/import'
import { apiFavoriteIds, apiFavorite, apiUnfavorite } from '@/api/favorite'
import { usePlayerStore } from '@/stores/player'
import { useDisplay } from '@/composables/useDisplay'
import SavePlaylistButton from '@/components/SavePlaylistButton.vue'
import { estimateCost, RATES_UPDATED } from '@/utils/pricing'

const { fmt } = useDisplay()
const player = usePlayerStore()

/** 推荐条目试听（有 has_preview 的才有按钮；旧报告没这个字段 → 不显示） */
function playRec(r) {
  player.play({
    trackId: r.track_id,
    name: r.name,
    artistNames: r.artist_names,
    albumId: r.album_id
  })
}

/**
 * 分析范围：分析哪些曲目，而不是「分析哪张歌单」。
 *
 * 收藏也算一个范围 —— 这个项目里导入和收藏是两件事（导入是搬一份列表来，
 * 收藏是我对这首歌表态），所以「只看我的收藏」是个自然的诉求，
 * 不该只能混在「全部」里。
 */
const MIN_ANALYZABLE = 20   // 和 agent-service 的 evidence.MIN_TRACKS 一致

// 维度名和置信度的显示映射。模板里直接引用，不需要是响应式的
const DIM_LABEL = {
  genre: '流派', era: '年代', artist: '常听艺人', mood_energy: '音乐能量',
  album_form: '专辑形态', duration: '曲目时长', diversity: '探索度',
  collaboration: '合作网络', region: '地区', unmatched: '未入库的那半边'
}
const CONF_LABEL = { high: '把握较大', medium: '中等', low: '仅供参考' }

// ============================================================
// 状态
// ============================================================

const provider = ref('deepseek')
const scope = ref('all')          // 'all' | 'favorites' | 'playlist:<importId>'
const playlists = ref([])         // 导入的歌单，带 matchedCount
const favCount = ref(null)        // 收藏曲目数。拿不到就是 null，不显示计数

// 推荐列表的收藏状态（2026-10-08）。**推荐列表原来只有 ▶，想收藏得跳到别的页** ——
// 真实反馈根本流不进来（评估时发现 240 条推荐 0 收藏，不是推荐没人要，是没通道）
const favIds = ref(new Set())
const favBusy = ref(null)

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
    favIds.value = new Set(favIds.value)   // 整体换新，模板里的 .has() 才重新求值
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    favBusy.value = null
  }
}
const reports = ref([])
const report = ref(null)          // { report: {...}, messages: [...] }
const runId = ref(null)
const run = ref(null)             // 当前轮询到的那条 run
const agentStatus = ref(null)

const loading = ref(true)
const busy = ref(false)           // 有请求在飞，锁住按钮
const error = ref('')

// 最近一次生成失败的原因。**必须单独存一份** —— 失败时 tick() 会去
// loadReports()，那里的 openReport 会把 run 清成 null，说明跟着一起没了
const lastFailure = ref('')

const question = ref('')
const asking = ref(false)

/** 生成已经跑了多少秒。几十秒的空白页是留不住用户的，必须给个数 */
const elapsed = ref(0)

/**
 * 预估总时长（进度条的分母）。**以后端返回的为准** ——
 * 原来两边各写一个（前端 30、后端 40），进度条的口径和文案对不上。
 * 后端 AgentService.ESTIMATE_SECONDS 是唯一来源，这里只是它还没到时的占位值
 */
const estimateSeconds = ref(30)

let pollTimer = null
let tickTimer = null

const POLL_MS = 3000

// 【轮询失败不能一次就停】见 tick() 的说明。5 次 × 3 秒 = 15 秒：
// 够跨过一次网络抖动，又不至于对着已经挂掉的后端一直打下去
const POLL_MAX_FAILURES = 5
let pollFailures = 0
const pollStopped = ref(false)    // 放弃轮询了，等用户点「重新连接」

// ============================================================
// 后端返回的是 JSON 列的字符串
// ============================================================
/**
 * agent_report 里的 report_json / data_scope_json 是 JSON 类型列，
 * Java 那边【原样透传不解析】，取出来是字符串。
 *
 * 这里两种都兼容一下：MyBatis 返回 Map 时列名保持 snake_case
 * （mapUnderscoreToCamelCase 只对实体类的属性生效，对 Map 不生效），
 * 所以字段名是 report_json / data_scope_json 而不是驼峰。
 */
function parseJson(maybe) {
  if (maybe == null) return null
  if (typeof maybe !== 'string') return maybe
  try {
    return JSON.parse(maybe)
  } catch (e) {
    return null
  }
}

const body = computed(() => parseJson(report.value?.report?.report_json))
const messages = computed(() => report.value?.messages || [])

// ============================================================
// 型（M8）：算出来的候选 + 用户认领的
// ============================================================

const showOther = ref(false)
const claiming = ref(false)
const claimError = ref('')

const candidates = computed(() => body.value?.persona_type_candidates || [])
const claimedName = computed(() => report.value?.report?.persona_type || '')

/**
 * 当前显示的型：认领过就用认领的，没认领就用系统算的最像那个。
 * 【两种状态必须区分显示】「你认领的」和「系统猜的」不是一回事 ——
 * 前者是用户的自我表达，后者只是算出来的。
 * 认领的型不在新报告候选里时（换了范围重新生成），只显示名字、desc 空缺。
 */
const currentType = computed(() => {
  const hit = candidates.value.find((c) => c.name === claimedName.value)
  if (hit) return hit
  if (claimedName.value) return { name: claimedName.value, desc: '' }
  return candidates.value[0] || null
})

const otherTypes = computed(() =>
  candidates.value.filter((c) => c.name !== currentType.value?.name))

async function claimType(name) {
  if (claiming.value || !report.value?.report?.id) return
  claiming.value = true
  claimError.value = ''
  try {
    await apiClaimType(report.value.report.id, name)
    // 本地改掉就够了（不重取整份报告）—— report 是 ref 里的对象，深响应
    report.value.report.persona_type = name
    showOther.value = false
  } catch (e) {
    claimError.value = e.response?.data?.message || e.message
  } finally {
    claiming.value = false
  }
}

/** 进度：已跑秒数 / 估计秒数。估计值只是给个参照，超了也不报错 */
const progress = computed(() =>
  Math.min(100, Math.round((elapsed.value / estimateSeconds.value) * 100))
)

/** 队列里这条还在跑吗。
 *
 * 【必须写在 script setup 里】写到 options 的 computed 里是读不到 run 这个 ref 的
 * （不同作用域），那种错误不会报错，只是永远返回 undefined，按钮就不会禁用。
 *
 * 【pollStopped 时必须算「没在跑」】轮询都断了，run.status 就永远停在
 * QUEUED/RUNNING 上不动了 —— 这时候还把它当依据，按钮会永久禁用，
 * 正是这次要修的那个「卡死在分析中」的症状。断线时把控制权还给用户，
 * 由「重新连接」那块说明情况。 */
const isRunning = computed(
  () => !pollStopped.value &&
    (run.value?.status === 'QUEUED' || run.value?.status === 'RUNNING')
)

// ============================================================
// 分析范围
// ============================================================

/**
 * 下拉选项。**能显示计数的都显示** —— 两个数差得很远是常态，
 * 814 首的「我喜欢的音乐」只有 427 首能分析（其余还没进本地库）。
 * 不显示的话用户点一张 0/76 的歌单，只会得到一句「数据不足」。
 */
const scopeOptions = computed(() => {
  const out = [
    { value: 'all', label: '全部（收藏 + 所有歌单）', disabled: false },
    {
      value: 'favorites',
      label: favCount.value == null ? '我的收藏' : `我的收藏（${favCount.value} 首）`,
      disabled: false
    }
  ]
  for (const p of playlists.value) {
    const n = p.matchedCount ?? 0
    out.push({
      value: `playlist:${p.id}`,
      label: `${p.playlistName}（${n} / ${p.trackCount} 首可分析）`,
      // 低于门槛的一定会走「数据不足」分支。置灰比让用户白等一趟好，
      // 但也只是提示 —— 后端才是真正说了算的那一方
      disabled: n < MIN_ANALYZABLE
    })
  }
  return out
})

function parseScope(value) {
  if (value.startsWith('playlist:')) {
    return { scopeKind: 'playlist', scopeRef: Number(value.slice('playlist:'.length)) }
  }
  return { scopeKind: value, scopeRef: null }
}

/** 正在跑的那一趟分析的是什么范围。进度面板上用 */
const runningScopeLabel = computed(() => {
  const kind = run.value?.scopeKind
  if (!kind) return ''
  if (kind === 'playlist') {
    const p = playlists.value.find((x) => x.id === run.value?.scopeRef)
    return p ? p.playlistName : '某张歌单'
  }
  return kind === 'favorites' ? '我的收藏' : '全部'
})

/** 已生成那份报告的范围名。**来自报告快照**，不是从当前选择推的 ——
 *  用户看完报告可能已经改了下拉 */
const reportScopeLabel = computed(() => report.value?.report?.scope_label || '')

/** 当前打开的报告 id（历史下拉的值）。没打开报告时空串，下拉显示空白 */
const currentReportId = computed(() => report.value?.report?.id ?? '')

/**
 * 本次生成的消耗（token / 估价 / 用时）。
 * 数据源：agent_report 的 tokens_in/tokens_out/latency_ms/llm_provider/llm_model ——
 * MyBatis 返回 Map 时列名保持 snake_case（见上面 parseJson 的注释）。
 * 【边界】数据不足的报告根本没调 LLM（tokens 全 null）→ 明说「没有调用模型」，
 * 不显示 0（0 会被读成「白嫖了」）；latency 缺失就整段不显示。
 */
const genCostText = computed(() => {
  const rep = report.value?.report
  if (!rep) return ''
  const hasTokens = rep.tokens_in != null || rep.tokens_out != null
  if (!hasTokens) {
    return rep.status === 'insufficient_data'
      ? '这份报告没有调用模型（数据不足，只做了统计）' : ''
  }
  const parts = []
  const who = [rep.llm_provider, rep.llm_model].filter(Boolean).join(' / ')
  if (who) parts.push(who)
  parts.push(`${(rep.tokens_in || 0).toLocaleString()} 进 / ${(rep.tokens_out || 0).toLocaleString()} 出`)
  const cost = estimateCost(rep.llm_provider, rep.llm_model, rep.tokens_in, rep.tokens_out)
  if (cost) parts.push(`≈ ${cost.text}`)
  if (rep.latency_ms) parts.push(`用时 ${(rep.latency_ms / 1000).toFixed(1)} 秒`)
  return '本次生成：' + parts.join(' · ')
})

/**
 * 历史下拉每一行的文案：意象名 · 日期。
 * 【名字用 headline 列】它存的是意象名（「深夜书桌前的一盏台灯」）——
 * 列表接口不拉 report_json（几十 KB × 每份），所以拿不到「型」。
 * 没有名字的报告（失败/降级前的）退化成 #id。
 */
function historyLabel(r) {
  const name = r.headline ? fmt(r.headline) : `报告 #${r.id}`
  return `${name} · ${shortDate(r.created_at)}`
}

/** 后端给的是 LocalDateTime 的 ISO 串（2026-10-07T11:32:00）→ 10-07 11:32 */
function shortDate(ts) {
  if (!ts) return ''
  const m = String(ts).match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : String(ts).slice(0, 10)
}

function onHistoryChange(e) {
  const id = Number(e.target.value)
  if (id) openReport(id)
}

/** 一份报告对应的下拉值。用于打开历史报告时把下拉切过去 */
function scopeValueOf(rep) {
  if (!rep) return 'all'
  if (rep.scope_kind === 'playlist' && rep.scope_ref != null) return `playlist:${rep.scope_ref}`
  return rep.scope_kind || 'all'
}

async function loadScopeOptions() {
  // 【两个请求各自 try】拉不到歌单不该让整个页面打不开，
  // 大不了下拉里只剩「全部」和「我的收藏」
  try {
    playlists.value = await apiListImports()
  } catch (e) {
    playlists.value = []
  }
  try {
    const ids = await apiFavoriteIds()
    favCount.value = ids.length
    favIds.value = new Set(ids)     // 顺手给推荐列表的 ♡ 用，不再多查一次
  } catch (e) {
    favCount.value = null
  }
}

// ============================================================
// 加载
// ============================================================

async function loadReports() {
  try {
    reports.value = await apiMyReports()
    // 默认打开最新那份 —— 用户回来就是想看上次的结果
    if (reports.value.length && !report.value) {
      await openReport(reports.value[0].id)
    }
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
}

async function openReport(id) {
  error.value = ''
  showOther.value = false
  claimError.value = ''
  try {
    report.value = await apiReportDetail(id)
    runId.value = null
    run.value = null
    // 【下拉跟着切到这份报告的范围】不切的话会出现「下拉写着『全部』、
    // 正文写着『分析范围 · 热歌榜』」—— 用户只会以为自己选错了。
    // 歌单已被删时那个选项不存在，就不动它（正文仍然显示快照里的名字）
    const v = scopeValueOf(report.value?.report)
    if (scopeOptions.value.some((o) => o.value === v)) scope.value = v
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  }
}

// ============================================================
// 生成
// ============================================================

async function generate() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  lastFailure.value = ''
  report.value = null
  elapsed.value = 0
  try {
    const { scopeKind, scopeRef } = parseScope(scope.value)
    const r = await apiRequestReport(provider.value, scopeKind, scopeRef)
    runId.value = r.runId
    if (r.estimateSeconds) estimateSeconds.value = r.estimateSeconds
    // 【先摆一条「排队中」的 run】从 runId 落值到第一次 tick 返回之间，
    // isRunning 还是 false —— 按钮短暂可点，连点两下会排两次 30 秒的 LLM 任务。
    // busy 挡不住：它在 finally 里就放开了，而 run 要等轮询回来才填上。
    //
    // 顺带解决另一个问题：进度条原来要等第一次轮询回来（约 3 秒）才出现，
    // 那几秒用户以为按钮没反应
    run.value = { id: r.runId, kind: 'report', status: 'QUEUED',
                  scopeKind, scopeRef, question: null }
    startPoll()
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    busy.value = false
  }
}

// ============================================================
// 轮询（和 MyPlaylistView 那套同一个形状）
// ============================================================

async function tick() {
  if (!runId.value) return
  try {
    const data = await apiRunStatus(runId.value)
    pollFailures = 0
    run.value = data.run
    if (data.report) {
      report.value = { report: data.report, messages: data.messages || [] }
    }
    if (data.run?.status === 'DONE' || data.run?.status === 'FAILED') {
      if (data.run.status === 'FAILED') {
        // 【先存下来再重载】下面的 loadReports() 会打开历史报告，
        // 而 openReport 会把 run 清成 null —— 失败说明跟着一起消失，
        // 用户就又看不到原因了
        lastFailure.value = data.run.errorMessage || '没有留下原因'
      }
      stopPoll()
      await loadReports()
    }
  } catch (e) {
    // 【一次抖动不能停表】原来的写法是这里直接 stopPoll()，
    // 注释写的是「不该把页面上的报告打断」—— 而停表恰恰就是打断：
    // run 还停在 RUNNING，isRunning 恒真，按钮永久显示「分析中…」，
    // 没有报错、没有重试，用户只能刷新页面。
    //
    // 所以改成「连续失败才停」，而且停下来的时候要把状态说清楚、
    // 给一个重连入口，不能静默地把控制权吞掉
    pollFailures += 1
    if (pollFailures >= POLL_MAX_FAILURES) {
      stopPoll()
      pollStopped.value = true
    }
  }
}

function startPoll() {
  if (pollTimer) return
  pollFailures = 0
  pollStopped.value = false
  tick()
  pollTimer = setInterval(tick, POLL_MS)
  tickTimer = setInterval(() => { elapsed.value += 1 }, 1000)
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  if (tickTimer) { clearInterval(tickTimer); tickTimer = null }
}

onUnmounted(stopPoll)

// ============================================================
// 追问
// ============================================================

async function ask() {
  const q = question.value.trim()
  if (!q || asking.value || !report.value) return
  asking.value = true
  error.value = ''
  try {
    const rep = report.value.report
    const r = await apiAsk(rep.id, q)
    question.value = ''
    // 追问也要排队，用同一个轮询。同样先摆一条，进度条不用等第一次轮询
    runId.value = r.runId
    run.value = { id: r.runId, kind: 'ask', status: 'QUEUED', question: q,
                  scopeKind: rep.scope_kind, scopeRef: rep.scope_ref }
    startPoll()
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    asking.value = false
  }
}

async function stopQueue() {
  busy.value = true
  try { agentStatus.value = await apiStopAgent() } catch (e) { /* 静默 */ }
  finally { busy.value = false }
}

async function resumeQueue() {
  busy.value = true
  try { agentStatus.value = await apiResumeAgent(); startPoll() } catch (e) { /* 静默 */ }
  finally { busy.value = false }
}

onMounted(async () => {
  // 【必须先 await 选项】loadReports 会顺手打开最新那份报告，
  // 而打开时要拿 scopeOptions 判断「该不该把下拉切过去」——
  // 两个并行的话选项还没到，那个判断静默失效
  await loadScopeOptions()
  loadReports()
})
</script>

<template>
  <h2>音乐人格</h2>
  <div class="rule"></div>

  <p class="muted">
    基于你的收藏和歌单，分析口味并推荐本地库里你还没听过的歌。
    <!-- 不写死秒数：进度条的分母来自后端，文案里再写一个数就会出现
         「文案说 30 秒、进度条按 40 秒走」这种对不上的情况 -->
    <strong>要跑半分钟左右</strong>，期间可以离开这个页面。
  </p>

  <div class="persona-bar">
    <select v-model="scope" class="scope-select" :disabled="busy || isRunning">
      <option
        v-for="o in scopeOptions"
        :key="o.value"
        :value="o.value"
        :disabled="o.disabled"
      >{{ o.label }}</option>
    </select>
    <select v-model="provider" :disabled="busy || isRunning">
      <option value="deepseek">DeepSeek</option>
      <option value="qwen">通义千问</option>
    </select>
    <button :disabled="busy || isRunning" @click="generate">
      {{ isRunning ? '分析中…' : '生成报告' }}
    </button>
    <!-- 【历史报告要能点开】原来这里只是一个「历史 N 份」的死文字 ——
         只能自动打开最新一份，更早的报告没有任何入口（用户报过）。
         换成下拉：选中即打开 -->
    <select
      v-if="reports.length"
      class="history-select"
      :value="currentReportId"
      :disabled="isRunning"
      :title="`历史报告 ${reports.length} 份`"
      @change="onHistoryChange"
    >
      <option v-for="r in reports" :key="r.id" :value="r.id">
        {{ historyLabel(r) }}
      </option>
    </select>
  </div>

  <p v-if="error" class="err">{{ error }}</p>

  <!-- 断线。**不能只是停表就完事** —— 停表之后 run 还停在 RUNNING，
       按钮会永久禁用，用户没有任何恢复的入口 -->
  <div v-if="pollStopped" class="err">
    <p>
      和服务器失去联系了（连着 {{ POLL_MAX_FAILURES }} 次没连上）。
      任务可能还在后台跑。
    </p>
    <button class="ghost sm" @click="startPoll">重新连接</button>
  </div>

  <!-- 进度。30 秒的空白页留不住用户，必须让他看见在动 -->
  <div v-else-if="isRunning" class="persona-progress">
    <div class="bar"><span :style="{ width: progress + '%' }"></span></div>
    <p class="muted">
      正在分析{{ runningScopeLabel ? '：' + runningScopeLabel : '…' }}
      <template v-if="run?.question">（回答追问）</template>
      · {{ elapsed }} 秒
    </p>
    <button class="ghost sm" :disabled="busy" @click="stopQueue">停止</button>
  </div>

  <!-- 生成失败。**失败和「降级」是两回事**：降级是产出了但砍掉了叙事，
       失败是什么都没产出。原来两条写在一个条件里，于是生成失败会显示
       「这份报告是降级版本」—— 一句和失败毫无关系的话。
       而且失败时 body 是 null，那条分支根本进不来，用户看到的是下面的
       「还没有报告」，只会以为是自己没点成功 -->
  <p v-if="lastFailure" class="err">
    报告没生成出来：{{ lastFailure }}
    <br />
    可以再点一次「生成报告」；如果反复失败，换一个模型试试。
  </p>

  <p v-if="loading" class="muted">加载中…</p>

  <p v-else-if="!body && !isRunning && !lastFailure" class="empty">
    还没有报告。点上面的「生成报告」跑一份。
  </p>

  <template v-else-if="body">
    <!-- 限宽容器：报告是长文，900 的页面宽度一行 40+ 个中文字会串行。
       720 是舒服的阅读宽度（见 style.css 的 .report-body） -->
    <div class="report-body">
    <!-- 这份是基于哪批歌生成的。**用报告里的快照**，不是当前下拉的值 ——
         用户看完一份报告可能已经把下拉改了，显示当前值会张冠李戴 -->
    <p v-if="reportScopeLabel" class="scope-note">
      分析范围 · {{ reportScopeLabel }}
    </p>

    <!-- 【型：报告的主角（M8）】固定池里算出来、认领后冻结。
         意象名（headline）降为它下面的注脚 ——「类别 + 个性」两层 -->
    <section v-if="currentType" class="ptype">
      <div class="ptype-head">
        <h3 class="ptype-name">{{ currentType.name }}</h3>
        <span v-if="claimedName" class="ptype-tag owned">你认领的</span>
        <span v-else class="ptype-tag guess">系统猜的</span>
      </div>
      <p v-if="currentType.desc" class="ptype-desc">{{ currentType.desc }}</p>

      <p v-if="otherTypes.length" class="ptype-more">
        <button v-if="!showOther" :disabled="claiming" @click="showOther = true">
          {{ claimedName ? '换一个' : `不是这个？看看另外 ${otherTypes.length} 个` }}
        </button>
      </p>
      <ul v-if="showOther" class="ptype-options">
        <li v-for="t in otherTypes" :key="t.name">
          <button :disabled="claiming" @click="claimType(t.name)">
            <span class="opt-name">{{ t.name }}</span>
            <span class="opt-desc">{{ t.desc }}</span>
          </button>
        </li>
      </ul>
      <p v-if="claimError" class="err">{{ claimError }}</p>
    </section>

    <h3 class="section-title persona-title">{{ fmt(body.headline?.title) }}</h3>
    <p class="muted">{{ fmt(body.headline?.subtitle) }}</p>

    <!-- 名字的依据。**这行是代码渲染的，不是模型写的** —— 名字是创作，
         它打哪儿来是事实。两个来源分开，名字就没法顺手把依据也编了 -->
    <p v-if="body.persona_basis" class="persona-basis">
      依据 · {{ body.persona_basis }}
    </p>

    <p v-if="report?.report?.status === 'degraded'" class="err">
      这份报告是降级版本：模型两次重写后仍有无法核实的内容，叙事部分被丢弃。
    </p>
    <p v-if="report?.report?.status === 'insufficient_data'" class="err">
      数据不够生成画像（曲目太少）。
    </p>

    <!-- 维度 -->
    <section v-for="(d, i) in body.dimensions || []" :key="i" class="persona-dim">
      <h4>
        {{ DIM_LABEL[d.dimension] || d.dimension }}
        <span class="conf" :class="d.confidence">{{ CONF_LABEL[d.confidence] }}</span>
      </h4>
      <p class="summary">{{ fmt(d.summary) }}</p>
      <ul class="claims">
        <li v-for="(c, j) in d.claims || []" :key="j">
          {{ fmt(c.text) }}
          <span v-if="c.basis === 'inference'" class="tag-infer" title="这一条是推断，不是实测">
            推断
          </span>
        </li>
      </ul>
    </section>

    <!-- 推荐 -->
    <section v-if="(body.recommendations || []).length" class="persona-dim">
      <h4>推荐给你的 {{ body.recommendations.length }} 首</h4>
      <ul class="rec-list">
        <li v-for="r in body.recommendations" :key="r.track_id" :data-track-id="r.track_id"
            :class="{ playing: player.isCurrent(r.track_id) }">
          <div class="row">
            <!-- 推荐的歌也能先试听 30 秒（没有试听源的不给按钮） -->
            <button
              v-if="r.has_preview"
              class="play"
              :class="{ on: player.isCurrent(r.track_id) }"
              :title="player.isCurrent(r.track_id) && player.playing ? '暂停' : '试听 30 秒'"
              @click="playRec(r)"
            >{{ player.isCurrent(r.track_id) && player.playing ? '❚❚' : '▶' }}</button>
            <span class="name">{{ fmt(r.name) || ('#' + r.track_id) }}</span>
            <span class="artist">{{ fmt(r.artist_names || r.artist) }}</span>
            <span v-if="r.matched_dimensions?.length" class="why">
              {{ r.matched_dimensions.map((m) => DIM_LABEL[m] || m).join(' · ') }}
            </span>
            <!-- 收藏通道：喜欢就直接收，不用跳去别的页 -->
            <button
              class="fav"
              :class="{ on: favIds.has(r.track_id) }"
              :disabled="favBusy === r.track_id"
              :title="favIds.has(r.track_id) ? '取消收藏' : '加入收藏'"
              @click="toggleFav(r.track_id)"
            >{{ favIds.has(r.track_id) ? '★' : '☆' }}</button>
          </div>
          <!-- 「为什么推荐」和「和你过去喜欢的有什么关系」是这个功能的卖点，
               不是装饰。原则 4 要求推荐必须能解释，所以这两行不能省 -->
          <p class="reason">{{ fmt(r.reason) }}</p>
          <p v-if="r.relation_to_history?.note" class="relation">
            和你的关系：{{ fmt(r.relation_to_history.note) }}
          </p>
        </li>
      </ul>
      <!-- 一键把这一批推荐存成歌单（和对话页共用一件；默认名用报告自己的意象名） -->
      <SavePlaylistButton
        :track-ids="body.recommendations.map((r) => r.track_id).filter(Boolean)"
        :default-name="body.headline?.title"
      />
    </section>

    <!-- 局限 -->
    <section v-if="(body.limitations || []).length" class="persona-dim limits">
      <h4>这套数据做不到什么</h4>
      <ul>
        <li v-for="(l, i) in body.limitations" :key="i">{{ fmt(l) }}</li>
      </ul>
    </section>

    <!-- 本次生成的消耗。数据一直在 API 里，只是从来没展示过 -->
    <p v-if="genCostText" class="muted gen-cost"
       :title="`估价按未缓存价、费率更新于 ${RATES_UPDATED}；缓存命中的输入会便宜得多`">
      {{ genCostText }}
    </p>

    <!-- 追问 -->
    <section class="persona-ask">
      <h4>追问</h4>
      <p class="muted">
        比如「我最常听哪个流派」「推荐里为什么有这首」「我听的东西偏老吗」
      </p>

      <ul v-if="messages.length" class="msg-list">
        <li v-for="m in messages" :key="m.id" :class="m.role">
          <span class="who">{{ m.role === 'user' ? '我' : '分析' }}</span>
          <span class="text">{{ fmt(m.content) }}</span>
        </li>
      </ul>

      <div class="ask-bar">
        <input
          v-model="question"
          class="ask-input"
          placeholder="问点什么…"
          :disabled="asking || isRunning"
          @keyup.enter="ask"
        />
        <button :disabled="asking || isRunning || !question.trim()" @click="ask">
          {{ asking ? '…' : '提问' }}
        </button>
      </div>
      <p v-if="asking || (isRunning && run?.question)" class="muted">正在查数据回答…</p>
    </section>
    </div>
  </template>
</template>
