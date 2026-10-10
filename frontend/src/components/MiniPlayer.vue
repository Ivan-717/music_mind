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

// 平台封面（歌单页的 coverUrl 是外链）会防盗链/过期，挂了就退回占位。
// 【watch 用 key 不用 trackId】未入库的歌没有 trackId —— 两首未入库歌之间
// 切换时 trackId 都是 undefined，封面就不会重置
const coverFailed = ref(false)
watch(() => player.track?.key, () => { coverFailed.value = false })

/** 点顶部进度条快进/快退（外链给的是整曲，没 seek 很难受） */
function seek(e) {
  const rect = e.currentTarget.getBoundingClientRect()
  player.seekTo((e.clientX - rect.left) / rect.width)
}
</script>

<template>
  <Transition name="mp">
    <div v-if="player.track" class="mini-player">
      <!-- 顶上一条琥珀进度线：正在发声的东西才亮 —— 全站的色彩语义到这才闭环。
           整条可以点：热区 10px（视觉线还是 2px），点哪跳哪 -->
      <div class="mp-progress" @click="seek">
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
