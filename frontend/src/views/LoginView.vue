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
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-box">
    <h1>MusicMind</h1>
    <h2>{{ isRegister ? '注册' : '登录' }}</h2>
    <form @submit.prevent="submit">
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
