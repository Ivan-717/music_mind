import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const KEY = 'mm_simplified'

export const useSettingsStore = defineStore('settings', () => {
  // 默认简体；只有显式存过 '0' 才是繁体
  const simplified = ref(localStorage.getItem(KEY) !== '0')

  watch(simplified, (v) => localStorage.setItem(KEY, v ? '1' : '0'))

  function toggle() {
    simplified.value = !simplified.value
  }

  return { simplified, toggle }
})
