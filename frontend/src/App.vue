<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { RouterView, RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useSettingsStore } from '@/stores/settings'
import { usePlayerStore } from '@/stores/player'
import MiniPlayer from '@/components/MiniPlayer.vue'

const settings = useSettingsStore()
const store = useUserStore()
const player = usePlayerStore()
const router = useRouter()
const route = useRoute()

const kw = ref('')

function doSearch() {
  const q = kw.value.trim()
  if (!q) return
  router.push({ path: '/search', query: { q } })
}

// 路由里的关键词回填到输入框：
// 这样从搜索结果页刷新、或点后退，输入框里还是刚才那个词
watch(
  () => route.query.q,
  (q) => { kw.value = q || '' },
  { immediate: true }
)

function logout() {
  store.clear()
  router.replace('/login')
}

// 刷新后把用户名找回来：token 在 localStorage 里活着，user 只在内存里（登录时赋值）——
// 不补这一下，导航栏右上角刷新就变空（fetchMe 内部自判 token/user，不会重复请求）
// 【被截断的文本，hover 出全名】全局事件委托：**按视觉判断**（有
// text-overflow: ellipsis 样式的元素），不认类名 —— 类名白名单永远追不全
// （实测踩过：专辑页头部的歌手名是 .album-meta 下的裸 span，带 .artist
// 类名的委托没覆盖它，用户一眼就发现了）；按样式判断则含未来一切截断元素。
// **只在真截断时挂**（scrollWidth > clientWidth）——没截断的行悬停弹一个
// 和可见内容一样的 tooltip 是噪音。每次 hover 重算：v-for 复用 DOM 时
// title 会带着上一行的旧值不放。
function onTruncatedOver(e) {
  const el = e.target
  if (!(el instanceof Element)) return
  if (getComputedStyle(el).textOverflow !== 'ellipsis') return
  const full = el.textContent.trim()
  if (el.scrollWidth > el.clientWidth) {
    if (full && el.title !== full) el.title = full
  } else if (el.title) {
    el.title = ''
  }
}

onMounted(() => {
  store.fetchMe()
  document.addEventListener('mouseover', onTruncatedOver)
})
onUnmounted(() => document.removeEventListener('mouseover', onTruncatedOver))
</script>

<template>
  <header v-if="store.token">
    <nav>
      <!-- 站名 = 电台呼号。左边那盏灯（on-air）常亮微呼吸：
           这是全站唯一的常驻动效，「电台还开着」 -->
      <RouterLink to="/albums" class="brand">
        <span class="on-air" aria-hidden="true"></span>MusicMind
      </RouterLink>
      <RouterLink to="/albums">专辑</RouterLink>
      <RouterLink to="/favorites">我的收藏</RouterLink>
      <RouterLink to="/import">导入歌单</RouterLink>
      <RouterLink to="/my-playlist">我的歌单</RouterLink>
      <RouterLink to="/explore">深夜电台</RouterLink>
      <RouterLink to="/persona">音乐人格</RouterLink>
      <input
        v-model="kw"
        class="nav-search"
        type="search"
        placeholder="搜索歌曲 / 专辑 / 歌手"
        @keyup.enter="doSearch"
      />
      <span class="who">{{ store.user?.username || '' }}</span>
      <button @click="settings.toggle()">
        {{ settings.simplified ? '简' : '繁' }}
      </button>
      <button @click="logout">退出</button>
    </nav>
  </header>
  <!-- 专辑页放宽：封面网格在 900px 里只能排 5 列，太挤。
       其它页保持 900 —— 文字行宽再宽就不好读了。
       has-player：播放条出现时给底部留位置（见 style.css），别盖住最后一行 -->
  <main :class="{ wide: route.name === 'albums', 'has-player': !!player.track }">
    <!-- 【切换页面淡入】
         mode="out-in" 是必须的：不加的话旧页面和新页面会同时在 DOM 里待一帧，
         整页高度闪一下。

         ⚠️ **中间那层 <div> 不是多余的，去掉它整个路由会变空白。**
         <Transition> 要求它的直接子节点是【单个元素】，而这个仓库的页面
         几乎都是多根节点（<h2> + <p> + <div>…）—— 直接放 <component> 的话
         Vue 会警告 "renders non-element root node that cannot be animated"，
         而 mode="out-in" 下旧页面出去了新页面进不来，**点导航变成白屏**。
         实测踩过：只有点链接才会发作，整页刷新（goto）不会 —— 所以
         「刷新才出页面」正是它的症状。
         :key 用 fullPath，换查询串（搜索页）也算新页面 -->
    <RouterView v-slot="{ Component }">
      <Transition name="page" mode="out-in">
        <div :key="route.fullPath">
          <component :is="Component" />
        </div>
      </Transition>
    </RouterView>
  </main>

  <!-- 播放条挂在 App 层（不在任何页面里）：切路由它不卸载，音乐不断 -->
  <MiniPlayer v-if="store.token" />
</template>
