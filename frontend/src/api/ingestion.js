import http from './http'

/**
 * 按需入库（③）：把本地库还没有的歌，按专辑从 MusicBrainz 抓进来。
 *
 * 为什么是「排队 + 轮询」而不是一个同步接口：一首歌要 6~7 秒
 * （搜录音 1s + 查专辑 1s + 子进程抓整张专辑 2s + 写库），
 * 整单几百首是几十分钟的事，同步接口只会转圈到超时。
 *
 * 队列是【全库共享】的——入库产物写进所有人共用的音乐侧表，
 * 所以别人排的队你也能看到进度（也因此看不到「谁排的」）。
 */

/**
 * 逐首入库。
 *
 * 返回 { total, queued, skippedAlreadyMatched, skippedQueued, skippedInvalid,
 *        queueCount, estimateSeconds }
 * 几个 skipped 分开报，是为了让用户明白「点了 30 首为什么只排进去 12 首」。
 *
 * @param trackRowIds user_playlist_track 的行 id（不是本地 track 的 id）
 */
export const apiQueueTracks = (trackRowIds) =>
  http.post('/ingestion/tracks', { trackRowIds })

/** 整单入库：这个歌单里所有还没对齐的曲目 */
export const apiQueueAll = (importId) =>
  http.post(`/ingestion/playlists/${importId}`)

/**
 * 队列状态。
 *
 * 返回 { paused, queueCount, currentJobId, currentLabel,
 *        activeTrackRowIds, recentJobs }
 * activeTrackRowIds 是【整个队列】的曲目行 id，用它把行标成「抓取中」——
 * 只靠 recentJobs 那几条会漏掉不在最近列表里的。
 */
export const apiIngestionStatus = () => http.get('/ingestion/status')

/** 停止。当前这条跑完就停，队列保留 */
export const apiStopIngestion = () => http.post('/ingestion/stop')

export const apiResumeIngestion = () => http.post('/ingestion/resume')
