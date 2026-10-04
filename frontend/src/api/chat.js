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
