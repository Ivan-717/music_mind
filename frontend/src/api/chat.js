import http from './http'
import { useUserStore } from '@/stores/user'

/**
 * 自由问答。
 *
 * 【和「追问」不是一条线】追问锚定某份报告（`/agent/ask`），
 * 这里锚定一个**会话**。两者共用 agent_message 表，靠挂在哪一列上区分。
 *
 * 形状和人格页那套一样：202 + 轮询（一次回答 20-40 秒，同步接口必然超时）。
 */

/**
 * 排一轮对话。
 *
 * @param message        用户说的那句话
 * @param conversationId 留空 = 新开一个会话
 * @returns { runId, conversationId }
 */
export const apiChat = (message, conversationId = null) =>
  http.post('/agent/chat', { message, conversationId })

/**
 * 订阅一轮 run 的实时进度（SSE，阶段 1：只有 stage 事件）。
 *
 * 【不用 EventSource】它带不了 Authorization 头（后端全部端点要 Bearer），
 * 所以走 fetch + ReadableStream 手写 SSE 帧解析。
 *
 * 【纯旁路】回答的正确性完全靠轮询 —— 这里断了/404（后端还没上）就静默，
 * 只是进度文案停住，绝不影响主流程。这是这个设计最要紧的一条边界。
 *
 * @returns abort 函数（停止轮询 / 组件卸载时调用）
 */
export function streamRun(runId, onNote) {
  const ctrl = new AbortController()
  const store = useUserStore()
  fetch(`/api/agent/runs/${runId}/stream`, {
    headers: { Authorization: 'Bearer ' + store.token },
    signal: ctrl.signal
  }).then(async (resp) => {
    if (!resp.ok || !resp.body) return
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // SSE 帧之间用空行分隔
      let cut
      while ((cut = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, cut)
        buf = buf.slice(cut + 2)
        const dataLine = frame.split('\n').find((l) => l.startsWith('data:'))
        if (!dataLine) continue
        try {
          onNote(JSON.parse(dataLine.slice(5).trim()).note)
        } catch (e) { /* 拆到半个帧就丢，等下一条 */ }
      }
    }
  }).catch(() => { /* 中断 / 404 —— 静默，轮询兜底 */ })
  return () => ctrl.abort()
}

/** 我的会话列表（不含消息，只给标题和条数） */
export const apiMyConversations = () => http.get('/agent/conversations')

/** 一个会话的全部消息。刷新页面靠它读回历史 */
export const apiConversationDetail = (id) => http.get(`/agent/conversations/${id}`)

/**
 * 把 Agent 提议的专辑抓进库。返回 { queued, skippedQueued, queueCount, importId, estimateSeconds }
 *
 * 【为什么抓取是前端的动作】Python 那边只「查上游、给候选」，抓不抓由用户点。
 * 一是 1 req/s，抓 5 张要 30-60 秒，用户得知道自己在等什么；
 * 二是让模型自己决定抓什么会抓飞。排队本身归 Java（ingestion_job 是它的队列表）。
 *
 * 落点是「AI 帮你找的」那张歌单 —— 在我的歌单页能看、能试听、能一键收藏。
 */
export const apiFetchUpstream = (proposals) =>
  http.post('/agent/fetch', { proposals })
