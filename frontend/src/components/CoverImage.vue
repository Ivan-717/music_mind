<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  albumId: { type: [Number, String], default: null },
  size: { type: Number, default: 56 },
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
    :src="`/covers/${albumId}.jpg`"
    :alt="alt"
    :width="size"
    :height="size"
    loading="lazy"
    decoding="async"
    @error="failed = true"
  />
  <div
    v-else
    class="cover cover-empty"
    :style="{ width: size + 'px', height: size + 'px' }"
    :title="alt ? `《${alt}》暂无封面` : '暂无封面'"
  >♪</div>
</template>

<style scoped>
.cover {
  display: block;
  flex: none;
  object-fit: cover;          /* 218×250 这种非正方形也能填满 */
  border-radius: 4px;
  background: #f2f2f2;
}
.cover-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ccc;
  font-size: 20px;
  border: 1px solid #eee;
}
</style>
