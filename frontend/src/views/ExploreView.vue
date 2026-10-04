<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiChat, apiMyConversations, apiConversationDetail, apiFetchUpstream } from '@/api/chat'
import { apiRunStatus } from '@/api/persona'
import { useDisplay } from '@/composables/useDisplay'

const { fmt } = useDisplay()

const conversations = ref([])
const current = ref(null)        // 会话 id
const messages = ref([])         // [{id, role, content}]
const question = ref('')

const loading = ref(true)
const busy = ref(false)
const error = ref('')
const elapsed = ref(0)

let pollTimer = null
let tickTimer = null

const POLL_MS = 3000
const ESTIMATE_SECONDS = 25
// 见 PersonaView 的说明：一次抖动不能停表，连续失败才停
const POLL_MAX_FAILURES = 5
let pollFailures = 0
const pollStopped = ref(false)

const running = ref(false)
const progress = computed(() =>
  Math.min(100, Math.round((elapsed.value / ESTIMATE_SECONDS) * 100))
)

/**
 * assistant 的消息内容是 JSON：{"answer": "...", "recommendations": [...]}。
 * **Java 那边原样透传不解析**，所以在这里解。user 的是纯文本。
 */
function parse(content) {
  const empty = { answer: content || '', recommendations: [], fetch_proposals: [] }
  if (typeof content !== 'string' || !content.trimStart().startsWith('{')) return empty
  try {
    const j = JSON.parse(content)
    return {
      answer: j.answer || '',
      recommendations: j.recommendations || [],
      // 没有提议时也要给个空数组 —— 模板里直接 .length，undefined 会炸
      fetch_proposals: j.fetch_proposals || []
    }
  } catch (e) {
    return empty
  }
}

/** 消息解析一次就够了。模板里直接 parse(m.content) 的话，每条要解三遍 */
const rendered = computed(() =>
  messages.value.map((m) => ({ id: m.id, role: m.role, ...parse(m.content) }))
)

const fetching = ref(false)
const fetched = ref('')

async function fetchAll(msg) {
  const list = msg.fetch_proposals || []
  if (!list.length || fetching.value) return
  fetching.value = true
  error.value = ''
  try {
    // 字段名转成 Java DTO 的驼峰 —— 那边不做 snake_case 兼容
    const r = await apiFetchUpstream(list.map((p) => ({
      releaseMbid: p.release_mbid, title: p.title, artist: p.artist,
      year: p.year, why: p.why
    })))
    const mins = Math.ceil((r.estimateSeconds || 0) / 60)
    fetched.value = `已排进队列 ${r.queued} 张`
      + (r.skippedQueued ? `，${r.skippedQueued} 张已经在队列里` : '')
      + `。约 ${mins} 分钟，抓完再问一次就有数据了。`
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    fetching.value = false
  }
}

// ============================================================
// 轮询
// ============================================================

async function tick() {
  try {
    const data = await apiRunStatus(currentRunId.value)
    pollFailures = 0
    if (data.run?.status === 'DONE' || data.run?.status === 'FAILED') {
      // 【只在结束时整段替换】跑的过程中服务端还没有刚落的那两条 ——
      // 每次都覆盖的话，本地乐观插进去的「我」那句话会在第一次轮询时消失
      if (data.messages) messages.value = data.messages
      if (data.run.status === 'FAILED') {
        error.value = `这一轮没答出来：${data.run.errorMessage || '没有留下原因'}`
      }
      stopPoll()
      loadConversations()
    }
  } catch (e) {
    // 一次抖动不停表；连续失败才停，并且要让用户看得见、点得动
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
  running.value = false
}

onUnmounted(stopPoll)

// ============================================================
// 会话
// ============================================================

const currentRunId = ref(null)

async function loadConversations() {
  try {
    conversations.value = await apiMyConversations()
  } catch (e) {
    /* 拉不到列表不该让整页打不开，还能新开一个问 */
  }
}

async function openConversation(id) {
  error.value = ''
  try {
    const data = await apiConversationDetail(id)
    current.value = id
    messages.value = data.messages || []
    currentRunId.value = null
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  }
}

function newConversation() {
  current.value = null
  messages.value = []
  error.value = ''
  currentRunId.value = null
}

async function send() {
  const q = question.value.trim()
  if (!q || busy.value || running.value) return
  busy.value = true
  error.value = ''
  elapsed.value = 0
  try {
    const r = await apiChat(q, current.value)
    current.value = r.conversationId
    currentRunId.value = r.runId
    // 【先把自己那句放上去】不然发出去到第一次轮询回来之间，页面像没反应
    messages.value = [...messages.value, { id: `local-${Date.now()}`, role: 'user', content: q }]
    question.value = ''
    running.value = true
    startPoll()
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  await loadConversations()
  // 默认打开最新那个会话 —— 回来就是想接着聊
  if (conversations.value.length) await openConversation(conversations.value[0].id)
  loading.value = false
})
</script>

<template>
  <h2>音乐探索</h2>
  <p class="muted">
    直接问，比如「我听得最多的是什么流派」「推荐几首安静的」。
    <strong>要跑 20-40 秒</strong>，问完可以离开这个页面。
  </p>

  <div class="explore-bar">
    <select
      class="conv-select"
      :value="current ?? ''"
      :disabled="running"
      @change="(e) => e.target.value === '' ? newConversation() : openConversation(Number(e.target.value))"
    >
      <option value="">＋ 新对话</option>
      <option v-for="c in conversations" :key="c.id" :value="c.id">
        {{ fmt(c.title) }}（{{ c.message_count }}）
      </option>
    </select>
    <button :disabled="running" @click="newConversation">新对话</button>
    <span class="muted">历史 {{ conversations.length }} 个</span>
  </div>

  <p v-if="error" class="err">{{ error }}</p>
  <p v-if="fetched" class="notice">{{ fetched }}</p>

  <div v-if="pollStopped" class="err">
    <p>和服务器失去联系了（连着 {{ POLL_MAX_FAILURES }} 次没连上）。任务可能还在后台跑。</p>
    <button class="ghost sm" @click="startPoll">重新连接</button>
  </div>

  <div v-else-if="running" class="persona-progress">
    <div class="bar"><span :style="{ width: progress + '%' }"></span></div>
    <p class="muted">正在查数据… {{ elapsed }} 秒</p>
  </div>

  <p v-if="loading" class="muted">加载中…</p>

  <p v-else-if="!rendered.length && !running" class="empty">
    还没有对话。下面问一句试试。
  </p>

  <ul v-else class="chat-list">
    <li v-for="m in rendered" :key="m.id" :class="m.role">
      <span class="who">{{ m.role === 'user' ? '我' : '分析' }}</span>
      <div class="body">
        <p class="text">{{ fmt(m.answer) }}</p>

        <ul v-if="m.recommendations.length" class="rec-list compact">
          <li v-for="r in m.recommendations" :key="r.track_id" :data-track-id="r.track_id">
            <div class="row">
              <span class="name">{{ fmt(r.name) || ('#' + r.track_id) }}</span>
              <span class="artist">{{ fmt(r.artist_names) }}</span>
            </div>
            <p v-if="r.reason" class="reason">{{ fmt(r.reason) }}</p>
          </li>
        </ul>

        <!-- 库里没有、但上游有。**抓不抓由用户点** —— 不自动抓 -->
        <ul v-if="m.fetch_proposals.length" class="fetch-list">
          <li class="fetch-head muted">
            这几张不在你库里，MusicBrainz 上有：
          </li>
          <li v-for="p in m.fetch_proposals" :key="p.release_mbid">
            <div class="row">
              <span class="name">{{ fmt(p.title) }}</span>
              <span class="artist">
                {{ fmt(p.artist) }}<template v-if="p.year"> · {{ p.year }}</template>
              </span>
            </div>
            <p v-if="p.why" class="reason">{{ fmt(p.why) }}</p>
          </li>
          <li class="fetch-action">
            <button :disabled="fetching || running" @click="fetchAll(m)">
              {{ fetching ? '排队中…' : `抓进库里（${m.fetch_proposals.length} 张）` }}
            </button>
          </li>
        </ul>
      </div>
    </li>
  </ul>

  <div class="ask-bar explore-ask">
    <input
      v-model="question"
      class="ask-input"
      placeholder="问点什么…"
      :disabled="busy || running"
      @keyup.enter="send"
    />
    <button :disabled="busy || running || !question.trim()" @click="send">
      {{ running ? '…' : '发送' }}
    </button>
  </div>
</template>
