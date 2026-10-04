<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  albumId: { type: [Number, String], default: null },
  size: { type: Number, default: 56 },
  /**
   * true = 撑满父容器并保持正方形（专辑网格用），此时忽略 size。
   *
   * 【为什么不直接在网格里写 <img>】组件里管着两件容易忘的事：
   * 加载失败后退成占位块（不然是一堆碎图标）、albumId 变了重置失败态
   * （同一条路由换参数时 Vue 会复用实例，上一张的失败态会粘着）。
   */
  fill: { type: Boolean, default: false },
  alt: { type: String, default: '' },
})

const failed = ref(false)

// albumId 变了要重置失败态：Vue Router 在同一条路由上换参数时
// 会复用组件实例，不重置的话「上一张没封面」会一直粘着
watch(() => props.albumId, () => {
  failed.value = false
})
</script>

<template>
  <img
    v-if="albumId && !failed"
    class="cover"
    :class="{ fill }"
    :src="`/covers/${albumId}.jpg`"
    :alt="alt"
    :width="fill ? undefined : size"
    :height="fill ? undefined : size"
    loading="lazy"
    decoding="async"
    @error="failed = true"
  />
  <div
    v-else
    class="cover cover-empty"
    :class="{ fill }"
    :style="fill ? undefined : { width: size + 'px', height: size + 'px' }"
    :title="alt ? `《${alt}》暂无封面` : '暂无封面'"
  >♪</div>
</template>

<style scoped>
/* 颜色走 style.css 的变量。**别在这里写死浅色** —— 暗底下 #f2f2f2 的
   占位块是一整块亮斑，比没有图还难看 */
.cover {
  display: block;
  flex: none;
  object-fit: cover;          /* 218×250 这种非正方形也能填满 */
  border-radius: 4px;
  background: var(--bg-lift);
}
.cover-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--mute);
  font-size: 20px;
  border: 1px solid var(--line);
}
/* 撑满父容器并保持正方形（专辑网格用）。此时 size 属性不参与 */
.cover.fill {
  width: 100%;
  height: auto;
  aspect-ratio: 1;
}
.cover-empty.fill { font-size: 26px; }
</style>
