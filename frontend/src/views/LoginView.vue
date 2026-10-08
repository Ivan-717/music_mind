<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { apiRegister } from '@/api/auth'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const isRegister = ref(false)
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

/**
 * 后端校验失败时返回的是
 *   {message: "参数校验失败", fields: {password: "密码长度需在 8-72 之间"}}
 * —— message 是笼统的，**具体哪个字段错了在 fields 里**。
 * 只显示 message 的话用户只知道「失败了」，不知道该改哪儿
 * （2026-10-07：短密码注册就是这个症状，只看到「参数校验失败」）
 */
function pickError(e) {
  const fields = e.response?.data?.fields
  if (fields && Object.keys(fields).length) {
    return Object.values(fields).join('；')
  }
  return e.response?.data?.message || e.message
}

async function submit() {
  error.value = ''
  loading.value = true
  try {
    if (isRegister.value) {
      await apiRegister(username.value, password.value)
    }
    await store.login(username.value, password.value)
    router.replace(route.query.redirect || '/albums')
  } catch (e) {
    error.value = pickError(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-box">
    <h1 class="login-station">
      <span class="on-air" aria-hidden="true"></span>MusicMind
    </h1>
    <p class="login-tag">一个凌晨还在播的私人电台</p>
    <div class="rule"></div>
    <h2>{{ isRegister ? '注册' : '登录' }}</h2>
    <form @submit.prevent="submit">
      <!-- 规则写在提交之前 —— 别让用户点一次才知道密码要 8 位 -->
      <p v-if="isRegister" class="form-hint">
        用户名 3-32 位（字母 / 数字 / 下划线）；密码至少 8 位
      </p>
      <input v-model="username" placeholder="用户名" autocomplete="username" />
      <input v-model="password" type="password" placeholder="密码"
             autocomplete="current-password" />
      <button type="submit" :disabled="loading">
        {{ loading ? '处理中…' : (isRegister ? '注册并登录' : '登录') }}
      </button>
    </form>
    <p v-if="error" class="err">{{ error }}</p>
    <a href="#" @click.prevent="isRegister = !isRegister">
      {{ isRegister ? '已有账号？去登录' : '没有账号？去注册' }}
    </a>
  </div>
</template>
