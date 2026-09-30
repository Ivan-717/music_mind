import { useSettingsStore } from '@/stores/settings'
import { toSimplified } from '@/utils/display'

/**
 * 毫秒 → m:ss。
 *
 * 0 / 负值 / null 一律显示 `--:--`：本地 track 表里 265 行 duration_ms 是 NULL，
 * 显示成 `0:00` 会让人以为是一首 0 秒的歌。
 */
export function fmtDuration(ms) {
  if (!ms || ms <= 0) return '--:--'
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** 平台标识 → 显示名。认不出的原样返回，不吞 */
export function providerLabel(p) {
  return p === 'netease' ? '网易云' : p === 'qq' ? 'QQ 音乐' : p
}

/**
 * 展示层文本格式化。只在模板里调用，不改任何数据。
 * fmt 内部读了 settings.simplified，所以开关一翻，所有用过它的模板自动重渲染，不用重新请求接口。
 */
export function useDisplay() {
  const settings = useSettingsStore()
  const fmt = (s) => (settings.simplified ? toSimplified(s) : s)
  return { fmt, fmtDuration, providerLabel, settings }
}
