import http from './http'

/**
 * 音乐人格报告 + 追问。
 *
 * 【路径是 /agent，不是 /persona】后端 Controller 的 RequestMapping 是
 * `/api/agent`。规格文档里写的 `/api/persona` 是动手前拍的名字，
 * 以实际实现为准。
 *
 * 【为什么是 202 + 轮询】一次报告要 30 秒（实测 p50 28.7s / p95 33.2s），
 * 而 axios 默认 timeout 是 10 秒 —— 同步接口必然超时。
 * 形状和「我的歌单」那套入库轮询一模一样，可以对着 MyPlaylistView 看。
 */

/**
 * 排一次报告生成。返回 { runId, estimateSeconds, scopeKind }。
 *
 * @param provider  deepseek / qwen
 * @param scopeKind all（收藏 + 全部歌单）/ favorites（只要收藏）/ playlist
 * @param scopeRef  scopeKind=playlist 时必填，是导入歌单的 id
 *
 * 【范围写进 run 行，不只靠参数传】Python 子进程只拿到一个 run-id，
 * 它得自己去库里读这一趟该分析什么。多一条传递路径就多一处可能不一致。
 *
 * 【越权】scopeRef 是自增 id，后端会校验归属，不是本人的歌单返回 404。
 */
export const apiRequestReport = (provider = 'deepseek', scopeKind = 'all', scopeRef = null) =>
  http.post('/agent/report', null, {
    params: { provider, scopeKind, ...(scopeRef == null ? {} : { scopeRef }) }
  })

/** 追问。返回 { runId } */
export const apiAsk = (reportId, question) =>
  http.post('/agent/ask', { reportId, question })

/**
 * 轮询一次运行。
 *
 * 返回 { run: {id, kind, status, question, reportId, provider, errorMessage, createdAt},
 *        report?: {...}, messages?: [...] }
 * run.status: QUEUED / RUNNING / DONE / FAILED
 *
 * report 只在 run 完成且报告存在时才有；messages 是这份报告的追问历史。
 */
export const apiRunStatus = (runId) => http.get(`/agent/runs/${runId}`)

/** 我生成过的报告（不含正文 —— 一份 report_json 有几十 KB） */
export const apiMyReports = () => http.get('/agent/reports')

/**
 * 按 id 取一份报告的正文 + 追问历史。
 *
 * 【为什么要这个接口】`/agent/runs/{id}` 要的是「运行 id」，
 * 而刷新页面时手里只有报告 id —— 光有列表读不回正文。
 * 「进程重启后历史还在」这条验收标准靠的就是它。
 */
export const apiReportDetail = (reportId) => http.get(`/agent/reports/${reportId}`)

/** 队列状态（全局共享，和别人生成的任务一起排队） */
export const apiAgentStatus = () => http.get('/agent/status')

export const apiStopAgent = () => http.post('/agent/stop')
export const apiResumeAgent = () => http.post('/agent/resume')
