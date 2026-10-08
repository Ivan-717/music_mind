<script setup>
import { ref, watch } from 'vue'
import { usePlayerStore } from '@/stores/player'
import { useDisplay } from '@/composables/useDisplay'
import CoverImage from '@/components/CoverImage.vue'

const player = usePlayerStore()
const { fmt } = useDisplay()

/** 秒 → m:ss。时长走等宽（--mono），在 CSS 里 */
function mmss(s) {
  if (!Number.isFinite(s)) return '0:00'
  const m = Math.floor(s / 60)
  const r = Math.floor(s % 60)
  return `${m}:${String(r).padStart(2, '0')}`
}

// 平台封面（歌单页的 coverUrl 是外链）会防盗链/过期，挂了就退回占位
const coverFailed = ref(false)
watch(() => player.track?.trackId, () => { coverFailed.value = false })
</script>

<template>
  <Transition name="mp">
    <div v-if="player.track" class="mini-player">
      <!-- 顶上一条琥珀进度线：正在发声的东西才亮 —— 全站的色彩语义到这才闭环 -->
      <div class="mp-progress">
        <span :style="{ width: (player.progress * 100) + '%' }"></span>
      </div>

      <div class="mp-inner">
        <img
          v-if="player.track.coverUrl && !coverFailed"
          class="mp-cover"
          :src="player.track.coverUrl"
          alt=""
          @error="coverFailed = true"
        />
        <CoverImage
          v-else-if="player.track.albumId"
          class="mp-cover"
          :album-id="player.track.albumId"
          :size="40"
          alt=""
        />
        <span v-else class="mp-cover placeholder">♪</span>

        <div class="mp-meta">
          <span class="mp-name">{{ fmt(player.track.name) }}</span>
          <span class="mp-artist">{{ fmt(player.track.artistNames) }}</span>
        </div>

        <span v-if="player.error" class="mp-error">{{ player.error }}</span>
        <template v-else>
          <button
            class="mp-toggle"
            :title="player.playing ? '暂停' : '播放'"
            @click="player.toggle()"
          >{{ player.playing ? '❚❚' : '▶' }}</button>
          <span class="mp-time">{{ mmss(player.current) }} / {{ mmss(player.duration) }}</span>
        </template>

        <button class="mp-close" title="关闭播放条" @click="player.close()">✕</button>
      </div>
    </div>
  </Transition>
</template>
