<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  apiRequestReport, apiAsk, apiRunStatus,
  apiMyReports, apiReportDetail,
  apiAgentStatus, apiStopAgent, apiResumeAgent
} from '@/api/persona'
import { useDisplay } from '@/composables/useDisplay'

const { fmt } = useDisplay()

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
const reports = ref([])
const report = ref(null)          // { report: {...}, messages: [...] }
const runId = ref(null)
const run = ref(null)             // 当前轮询到的那条 run
const agentStatus = ref(null)

const loading = ref(true)
const busy = ref(false)           // 有请求在飞，锁住按钮
const error = ref('')
const notice = ref('')

// 最近一次生成失败的原因。**必须单独存一份** —— 失败时 tick() 会去
// loadReports()，那里的 openReport 会把 run 清成 null，说明跟着一起没了
const lastFailure = ref('')

const question = ref('')
const asking = ref(false)

/** 生成已经跑了多少秒。30 秒的空白页是留不住用户的，必须给个数 */
const elapsed = ref(0)

let pollTimer = null
let tickTimer = null

const POLL_MS = 3000
const ESTIMATE_SECONDS = 30

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
  Math.min(100, Math.round((elapsed.value / ESTIMATE_SECONDS) * 100))
)

/** 队列里这条还在跑吗。**必须写在 script setup 里** ——
 * 写到 options 的 computed 里是读不到 run 这个 ref 的（不同作用域），
 * 那种错误不会报错，只是永远返回 undefined，按钮就不会禁用 */
const isRunning = computed(
  () => run.value?.status === 'QUEUED' || run.value?.status === 'RUNNING'
)

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
  notice.value = ''
  lastFailure.value = ''
  report.value = null
  elapsed.value = 0
  try {
    const r = await apiRequestReport(provider.value)
    runId.value = r.runId
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
    const r = await apiAsk(report.value.report.id, q)
    question.value = ''
    // 追问也要排队，用同一个轮询
    runId.value = r.runId
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

onMounted(loadReports)
</script>

<template>
  <h2>音乐人格</h2>

  <p class="muted">
    基于你的收藏和歌单，分析口味并推荐本地库里你还没听过的歌。
    <strong>要跑 30 秒左右</strong>，期间可以离开这个页面。
  </p>

  <div class="persona-bar">
    <select v-model="provider" :disabled="busy">
      <option value="deepseek">DeepSeek</option>
      <option value="qwen">通义千问</option>
    </select>
    <button :disabled="busy || isRunning" @click="generate">
      {{ isRunning ? '分析中…' : '生成报告' }}
    </button>
    <span v-if="reports.length" class="muted">历史 {{ reports.length }} 份</span>
  </div>

  <p v-if="error" class="err">{{ error }}</p>
  <p v-if="notice" class="notice">{{ notice }}</p>

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
      正在分析… {{ elapsed }} 秒
      <template v-if="run?.question">（回答追问）</template>
      · {{ agentStatus?.currentLabel || '排队中' }}
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
    <h3 class="section-title">{{ fmt(body.headline?.title) }}</h3>
    <p class="muted">{{ fmt(body.headline?.subtitle) }}</p>

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
