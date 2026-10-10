<script setup>
/**
 * 「存成歌单」按钮 —— 对话页和报告页共用（原来只有对话页有，且用 window.prompt）。
 *
 * 【为什么内联命名】window.prompt 在移动端 webview 里会被直接拦截，而且
 * 取消后没有任何反馈。改成行内输入，Enter 保存、Esc 取消。
 *
 * 【保存成功给跳转链接】原来只提示一句「已存成歌单 x」——歌单存到哪去了？
 * 全站都没有页面列它（那就是"造了看不见"的病）。现在链接到
 * 「我的歌单 → 我建的」，一条闭环。
 */
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiCreatePlaylistFromTracks } from '@/api/playlist'

const props = defineProps({
  trackIds: { type: Array, required: true },
  /** 默认名。对话页传"上一句问的话"，报告页传意象名 */
  defaultName: { type: String, default: 'AI 推荐' },
  /** 按钮文案（不传按首数生成） */
  label: { type: String, default: '' }
})

const naming = ref(false)
const nameText = ref('')
const saving = ref(false)
const error = ref('')
const saved = ref(null)      // { id, name, added, skipped }

function start() {
  nameText.value = (props.defaultName || 'AI 推荐').replace(/\s+/g, ' ').slice(0, 24)
  saved.value = null
  error.value = ''
  naming.value = true
}

async function submit() {
  const name = nameText.value.trim()
  if (!name || saving.value) return
  saving.value = true
  error.value = ''
  try {
    saved.value = await apiCreatePlaylistFromTracks(name, props.trackIds)
    naming.value = false
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <p class="save-row">
    <template v-if="naming">
      <input
        v-model="nameText"
        class="ask-input inline-name"
        maxlength="80"
        placeholder="歌单叫什么？"
        @keyup.enter="submit"
        @keyup.esc="naming = false"
      />
      <button :disabled="saving || !nameText.trim()" @click="submit">
        {{ saving ? '保存中…' : '保存' }}
      </button>
      <button :disabled="saving" @click="naming = false">取消</button>
    </template>

    <template v-else-if="saved">
      <span class="notice">
        已存成歌单「{{ saved.name }}」，{{ saved.added }} 首<template
          v-if="saved.skipped">（{{ saved.skipped }} 首库里已不存在，跳过）</template>
        · <RouterLink :to="`/my-playlist?source=created&playlist=${saved.id}`">去看看</RouterLink>
      </span>
    </template>

    <template v-else>
      <button @click="start">{{ label || `存成歌单（${trackIds.length} 首）` }}</button>
    </template>
  </p>
  <p v-if="error" class="err">{{ error }}</p>
</template>
