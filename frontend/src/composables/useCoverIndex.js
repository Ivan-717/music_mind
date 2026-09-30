import { ref } from 'vue'

/**
 * 哪些专辑有封面。
 *
 * 数据来自封面管道生成的 /covers/_manifest.json——它和图片文件放在一起，
 * 由前端静态托管。这样不需要后端加字段，也不需要新接口。
 *
 * 模块级单例：整个应用只 fetch 一次，多个组件共享同一个 Set。
 */
const withCover = ref(new Set())
let loading = null

function load() {
  if (loading) return loading

  loading = fetch('/covers/_manifest.json')
    .then((r) => (r.ok ? r.json() : {}))
    .then((manifest) => {
      const ids = new Set()
      for (const [id, info] of Object.entries(manifest)) {
        if (info && (info.status === 'ok' || info.status === 'existing')) {
          ids.add(Number(id))
        }
      }
      withCover.value = ids
    })
    .catch(() => {
      // 拿不到 manifest 就不排序，页面照常显示（19/250 没有封面，不值得为它报错）
    })

  return loading
}

export function useCoverIndex() {
  load()
  return { withCover }
}
