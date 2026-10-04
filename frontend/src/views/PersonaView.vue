<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  apiRequestReport, apiAsk, apiRunStatus,
  apiMyReports, apiReportDetail,
  apiAgentStatus, apiStopAgent, apiResumeAgent
} from '@/api/persona'
import { apiListImports } from '@/api/import'
import { apiFavoriteIds } from '@/api/favorite'
import { useDisplay } from '@/composables/useDisplay'

const { fmt } = useDisplay()

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
  collaboration: '合作网络', region: '地区'
}
const CONF_LABEL = { high: '把握较大', medium: '中等', low: '仅供参考' }

// ============================================================
// 状态
// ============================================================

const provider = ref('deepseek')
const scope = ref('all')          // 'all' | 'favorites' | 'playlist:<importId>'
const playlists = ref([])         // 导入的歌单，带 matchedCount
const favCount = ref(null)        // 收藏曲目数。拿不到就是 null，不显示计数
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
    favCount.value = (await apiFavoriteIds()).length
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
    <span v-if="reports.length" class="muted">历史 {{ reports.length }} 份</span>
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
    <!-- 这份是基于哪批歌生成的。**用报告里的快照**，不是当前下拉的值 ——
         用户看完一份报告可能已经把下拉改了，显示当前值会张冠李戴 -->
    <p v-if="reportScopeLabel" class="scope-note">
      分析范围 · {{ reportScopeLabel }}
    </p>

    <h3 class="section-title">{{ fmt(body.headline?.title) }}</h3>
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
        <li v-for="r in body.recommendations" :key="r.track_id" :data-track-id="r.track_id">
          <div class="row">
            <span class="name">{{ fmt(r.name) || ('#' + r.track_id) }}</span>
            <span class="artist">{{ fmt(r.artist_names || r.artist) }}</span>
            <span v-if="r.matched_dimensions?.length" class="why">
              {{ r.matched_dimensions.map((m) => DIM_LABEL[m] || m).join(' · ') }}
            </span>
          </div>
          <!-- 「为什么推荐」和「和你过去喜欢的有什么关系」是这个功能的卖点，
               不是装饰。原则 4 要求推荐必须能解释，所以这两行不能省 -->
          <p class="reason">{{ fmt(r.reason) }}</p>
          <p v-if="r.relation_to_history?.note" class="relation">
            和你的关系：{{ fmt(r.relation_to_history.note) }}
          </p>
        </li>
      </ul>
    </section>

    <!-- 局限 -->
    <section v-if="(body.limitations || []).length" class="persona-dim limits">
      <h4>这套数据做不到什么</h4>
      <ul>
        <li v-for="(l, i) in body.limitations" :key="i">{{ fmt(l) }}</li>
      </ul>
    </section>

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
  </template>
</template>
