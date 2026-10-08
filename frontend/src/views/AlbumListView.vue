<script setup>
import { ref, computed, onMounted } from 'vue'
import { apiAlbums } from '@/api/auth'
import { useDisplay } from '@/composables/useDisplay'
import CoverImage from '@/components/CoverImage.vue'

const { fmt } = useDisplay()

const albums = ref([])
const error = ref('')
const loading = ref(true)

/**
 * 封面清单：`/covers/_manifest.json`（`fetch_covers.py` 每抓完一轮就重写它）。
 * 形如 `{"10": {"status": "existing"}, "99": {"status": "no_cover"}}`。
 *
 * 【为什么不用 <img> 的 error 事件】第一版就是那么写的，结果是
 * **只滤掉 4 张而不是 97 张** —— 因为 `loading="lazy"` 让没滚到的图
 * 根本不加载，也就永远不会触发 error。表现是「边滚边消失」，
 * 用户在滚动时看着卡片一张张跳掉。
 *
 * 清单是渲染【之前】就知道的，布局稳定，也不多发 97 个必然失败的请求。
 */
const covers = ref(null)

/** 封面加载失败的（清单里没有的新专辑走这条路兜底，见 onCoverError） */
const failedIds = ref({})

/**
 * 真正渲染的那些。
 *
 * 清单里**查不到的按「有封面」处理** —— 那是「抓完清单之后才入库的新专辑」。
 * 宁可显示一个拿不到图的占位块，也不要让一张真实存在的专辑凭空消失。
 */
const visible = computed(() => albums.value.filter((a) => {
  if (failedIds.value[a.id]) return false
  const status = covers.value?.[a.id]?.status
  return status !== 'no_cover'
}))

function onCoverError(id) {
  failedIds.value = { ...failedIds.value, [id]: true }
}

async function loadCovers() {
  try {
    covers.value = await (await fetch('/covers/_manifest.json')).json()
  } catch (e) {
    // 拿不到清单就全都显示 —— 退化成「有占位块」的旧行为，而不是白屏
    covers.value = null
  }
}

onMounted(async () => {
  loadCovers()
  try {
    // 年份在这里切一次，不在模板里对同一行调两遍 slice
    albums.value = (await apiAlbums()).map((a) => ({   // 拦截器已经吐过 data 了
      ...a,
      year: a.releaseDate ? String(a.releaseDate).slice(0, 4) : ''
    }))
  } catch (e) {
    error.value = e.response?.data?.message || e.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="album-grid-head">
    <h2>专辑</h2>
    <span v-if="!loading && !error" class="count">{{ visible.length }} 张</span>
  </div>
  <div class="rule"></div>

  <p v-if="loading" class="muted">加载中…</p>
  <p v-else-if="error" class="err">{{ error }}</p>

  <!--
    网格而不是列表：封面是这一页唯一有信息量的东西，列表里的 56px 缩略图
    等于把 471 张封面压成一列小方块，既看不清也翻不完。
  -->
  <ul v-else class="album-grid">
    <li v-for="a in visible" :key="a.id">
      <RouterLink class="card" :to="`/albums/${a.id}`">
        <CoverImage :album-id="a.id" fill :alt="fmt(a.name)"
                    @error="onCoverError(a.id)" />
        <span class="card-name">{{ fmt(a.name) }}</span>
        <span class="card-sub">
          {{ fmt(a.artistNames) }}<template v-if="a.year"> · {{ a.year }}</template>
        </span>
      </RouterLink>
    </li>
  </ul>
</template>
