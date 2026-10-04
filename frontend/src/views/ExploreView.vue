<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiChat, apiMyConversations, apiConversationDetail } from '@/api/chat'
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
  if (typeof content !== 'string' || !content.trimStart().startsWith('{')) {
    return { answer: content || '', recommendations: [] }
  }
  try {
    return JSON.parse(content)
  } catch (e) {
    return { answer: content, recommendations: [] }
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

  <div v-if="pollStopped" class="err">
    <p>和服务器失去联系了（连着 {{ POLL_MAX_FAILURES }} 次没连上）。任务可能还在后台跑。</p>
    <button class="ghost sm" @click="startPoll">重新连接</button>
  </div>

  <div v-else-if="running" class="persona-progress">
    <div class="bar"><span :style="{ width: progress + '%' }"></span></div>
    <p class="muted">正在查数据… {{ elapsed }} 秒</p>
  </div>

  <p v-if="loading" class="muted">加载中…</p>

  <p v-else-if="!messages.length && !running" class="empty">
    还没有对话。下面问一句试试。
  </p>

  <ul v-else class="chat-list">
    <li v-for="m in messages" :key="m.id" :class="m.role">
      <span class="who">{{ m.role === 'user' ? '我' : '分析' }}</span>
      <div class="body">
        <p class="text">{{ fmt(parse(m.content).answer) }}</p>
        <ul v-if="parse(m.content).recommendations.length" class="rec-list compact">
          <li v-for="r in parse(m.content).recommendations" :key="r.track_id" :data-track-id="r.track_id">
            <div class="row">
              <span class="name">{{ fmt(r.name) || ('#' + r.track_id) }}</span>
              <span class="artist">{{ fmt(r.artist_names) }}</span>
            </div>
            <p v-if="r.reason" class="reason">{{ fmt(r.reason) }}</p>
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
