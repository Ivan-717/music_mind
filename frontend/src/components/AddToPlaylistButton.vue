<script setup>
/**
 * 「加入歌单」按钮 —— 推荐行（对话页 + 报告页）共用。
 *
 * 【为什么是下拉选已有歌单，不是又一个命名框】这个名字的场景是「逐首精挑」：
 * 用户已经有一张歌单（「深夜收藏夹」），想把这一首放进去。整批存的场景
 * 归 SavePlaylistButton（新建一张、批量灌）。没有自建歌单时，给一条去
 * 「我的歌单」新建的链接 —— 不在行内缠一个输入框。
 *
 * 【后端已幂等】playlistMapper.addTrack 是 ON DUPLICATE KEY UPDATE ——
 * 重复加不报错；✓ 标记只是这一轮的 UI 反馈。
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { RouterLink } from 'vue-router'
import { apiMyPlaylists, apiAddTrackToPlaylist } from '@/api/playlist'

const props = defineProps({
  trackId: { type: Number, default: null },
  /** 未入本地库的行（导入歌单里没对齐的）禁用 —— 和收藏键同款行为 */
  disabled: { type: Boolean, default: false }
})

const open = ref(false)
const lists = ref(null)        // null = 还没拉过
const busy = ref(null)
const done = ref(new Set())    // 这一轮点过 ✓ 的歌单（可能加进多张）
const error = ref('')
const wrap = ref(null)

async function toggle() {
  if (props.disabled) return
  open.value = !open.value
  error.value = ''
  if (open.value && lists.value === null) {
    try {
      lists.value = await apiMyPlaylists()
    } catch (e) {
      lists.value = []
      error.value = e.response?.data?.message || e.message
    }
  }
}

async function add(list) {
  if (busy.value) return
  busy.value = list.id
  error.value = ''
  try {
    await apiAddTrackToPlaylist(list.id, props.trackId)
    done.value = new Set(done.value).add(list.id)
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    busy.value = null
  }
}

/** 点面板外面收起（不做的话面板会一直挂在行上） */
function onDocClick(e) {
  if (open.value && wrap.value && !wrap.value.contains(e.target)) open.value = false
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <span ref="wrap" class="addpl-wrap" @click.stop>
    <button
      class="fav addpl"
      :class="{ on: open || done.size }"
      :disabled="disabled"
      :title="disabled ? '还没进本地库，暂时加不了歌单' : '加入歌单'"
      @click="toggle"
    >加入歌单</button>
    <div v-if="open" class="addpl-panel">
      <p v-if="lists === null" class="muted">加载中…</p>
      <p v-else-if="!lists.length" class="muted">
        还没有自建歌单 ——
        <RouterLink to="/my-playlist?source=created">去新建一张</RouterLink>
      </p>
      <template v-else>
        <button
          v-for="p in lists"
          :key="p.id"
          :disabled="!!busy"
          @click="add(p)"
        >
          <span class="addpl-name">{{ p.name }}</span>
          <span v-if="done.has(p.id)" class="addpl-done">✓ 已加入</span>
          <span v-else-if="p.trackCount != null" class="muted">{{ p.trackCount }} 首</span>
        </button>
      </template>
      <p v-if="error" class="err">{{ error }}</p>
    </div>
  </span>
</template>
