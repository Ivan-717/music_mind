import http from './http'

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
