package com.musicmind.service;

import com.musicmind.config.IngestionProperties;
import com.musicmind.entity.IngestionJob;
import com.musicmind.entity.UserPlaylistTrack;
import com.musicmind.mapper.ImportMapper;
import com.musicmind.mapper.IngestionJobMapper;
import com.musicmind.mapper.UserPlaylistMapper;
import com.musicmind.util.ArtistText;
import com.musicmind.util.KeywordVariants;
import com.musicmind.vo.MbReleaseCandidateVO;
import com.musicmind.vo.RematchCandidateVO;
import com.musicmind.vo.TrackMatchVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.SmartLifecycle;
import org.springframework.stereotype.Component;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 按需入库的执行者：单线程顺序消费 ingestion_job。
 *
 * 【为什么是单线程】MusicBrainz 限速 1 请求/秒，并发跑只是排队等限速，
 * 还会让失败原因变得难以复现。一条一条来，一小时几十首，够用。
 *
 * 【分工】Java 负责解析（找 release）+ 排队 + 重对齐，Python 负责写库。
 * 音乐侧的表归 data-pipeline 写（见 schema-user.sql 头注释），
 * 在这儿用 Java 重写一遍入库逻辑，两边迟早漂移。
 *
 * 【和 IngestionService 的分工】Service 管「排队和查询」，Worker 管「跑」。
 * Worker 不依赖 Service，避免循环依赖。
 *
 * 【测试里必须关掉】ingestion.worker-enabled=false。@SpringBootTest 会起整个上下文，
 * 包括这个 worker —— 本地队列里躺着几百条任务时跑 mvn test，测试会真的去消费队列、
 * 起子进程、往库里写东西。用户跑测试不该改数据。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class IngestionWorker implements SmartLifecycle {

    private final IngestionJobMapper jobMapper;
    private final UserPlaylistMapper userPlaylistMapper;
    private final ImportMapper importMapper;
    private final ImportService importService;
    private final MusicBrainzLookupService lookupService;
    private final IngestionProperties props;

    private final AtomicBoolean alive = new AtomicBoolean(false);
    private final AtomicBoolean paused = new AtomicBoolean(false);

    /** 清扫卡死任务的间隔。它是一条小范围 UPDATE，但没必要每轮循环都跑 */
    private static final long SWEEP_INTERVAL_MS = 60_000;

    private volatile Thread thread;
    private volatile Long currentJobId;
    private volatile String currentLabel;
    private long lastSweepAt = 0;

    // ============================================================
    // 生命周期
    // ============================================================

    /**
     * 测试里不自动启动（ingestion.worker-enabled=false）。
     *
     * 【为什么不是把 bean 整个去掉】IngestionService 构造器依赖它，
     * @ConditionalOnProperty 一关上下文就起不来。保留 bean、只是不启动线程，
     * 依赖关系和接口行为都不变，但队列不会被动。
     */
    @Override
    public boolean isAutoStartup() {
        return props.isWorkerEnabled();
    }

    @Override
    public void start() {
        if (!alive.compareAndSet(false, true)) {
            return;
        }
        thread = new Thread(this::loop, "ingestion-worker");
        thread.setDaemon(true);
        thread.start();
        log.info("按需入库 worker 已启动");
    }

    @Override
    public void stop() {
        alive.set(false);
        Thread t = thread;
        if (t != null) {
            t.interrupt();
        }
    }

    @Override
    public boolean isRunning() {
        return alive.get();
    }

    /** 暂停标志。当前这条跑完才停，队列保留 */
    public boolean isPaused() {
        return paused.get();
    }

    public void pause() {
        paused.set(true);
    }

    public void resume() {
        paused.set(false);
    }

    public Long getCurrentJobId() {
        return currentJobId;
    }

    public String getCurrentLabel() {
        return currentLabel;
    }

    // ============================================================
    // 主循环
    // ============================================================

    private void loop() {
        try {
            runLoop();
        } catch (Throwable t) {
            // 【连 Error 也要兜住】线程死了但 isRunning() 还返回 true 是最糟的组合：
            // Spring 认为它活着不会重启，队列从此不再被消费，而界面上一点异常都看不出来
            log.error("入库 worker 异常退出，队列已停止消费（需重启后端）", t);
        } finally {
            alive.set(false);
        }
    }

    private void runLoop() {
        // 崩溃恢复：上一次进程没了，被领走的任务还挂在 RUNNING，先打回队列。
        // 没有这一步，那些任务会永远显示「抓取中」，重排还会被去重挡掉
        int requeued = jobMapper.requeueRunning();
        if (requeued > 0) {
            log.info("把 {} 条上次没跑完的任务打回队列", requeued);
        }

        while (alive.get()) {
            sweepStale();
            try {
                if (paused.get()) {
                    idle();
                    continue;
                }

                IngestionJob job = jobMapper.selectNextQueued();
                if (job == null) {
                    idle();
                    continue;
                }
                if (jobMapper.claim(job.getId()) == 0) {
                    continue;   // 被别的实例抢走了，下一轮再看
                }

                process(job);

            } catch (Exception e) {
                // 单条任务的异常在 process 里已经收口了，能漏到这儿的是
                // 数据库断了之类的循环级故障——不能让 worker 线程整个死掉
                log.warn("入库 worker 单轮异常，稍后重试", e);
                idle();
            }
        }
    }

    /**
     * 把卡死的 RUNNING 打回队列。每轮循环都调，但内部限流成最多 60 秒扫一次。
     *
     * 【为什么需要它】requeueRunning 只在启动时跑一次。如果 finish() 自己失败
     * （MySQL 抖一下、连接池超时、死锁被 kill），那条任务就永远停在 RUNNING：
     * 前端一直显示「抓取中」，而 countActiveByTrackRow 又把同一行的重排挡掉，
     * 用户点什么都没用，只能重启后端。这里按「挂了多久」兜住。
     */
    private void sweepStale() {
        long now = System.currentTimeMillis();
        if (now - lastSweepAt < SWEEP_INTERVAL_MS) {
            return;
        }
        lastSweepAt = now;

        // 超过 2 倍超时时间还挂在 RUNNING 的必然是卡死：
        // 正常任务到点会被 destroyForcibly 强杀并收尾，不可能跑这么久
        try {
            int n = jobMapper.requeueStale(props.getJobTimeoutSeconds() * 2L);
            if (n > 0) {
                log.warn("把 {} 条卡死的 RUNNING 任务打回队列", n);
            }
        } catch (Exception e) {
            // 清扫失败不能影响正常消费，下一轮再来
            log.warn("清扫卡死任务失败：{}", e.toString());
        }
    }

    private void idle() {
        try {
            Thread.sleep(props.getPollIntervalMs());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            alive.set(false);
        }
    }

    // ============================================================
    // 单条任务
    // ============================================================

    private void process(IngestionJob job) {
        currentJobId = job.getId();
        currentLabel = job.getArtistName() + " - " + job.getTitle();
        long startedAt = System.currentTimeMillis();

        try {
            // ① 先看看本地库现在有没有这一首。
            //
            // 排队时还没有、现在有了——两种可能：
            //   · 这一行已经被别的任务的重匹配顺手解决了（同一个歌手往往排了好几条）
            //   · 这张专辑刚被别的任务抓进来，这首正好也在里面
            // 两种都能直接对上，省掉整套网络往返。查一次 SQL 十几毫秒，
            // 而一次 MusicBrainz 往返要 2~3 秒（限速 1 请求/秒），完全值得先试
            UserPlaylistTrack row = userPlaylistMapper.findTrackRow(job.getTrackRowId(), job.getUserId());
            if (row != null) {
                TrackMatchVO local = importService.match(
                        row.getTitle(), ArtistText.primary(row.getArtists()), row.getDurationMs());
                if (local != null) {
                    userPlaylistMapper.updateMatch(
                            row.getImportId(), row.getExternalId(), "MATCHED", local.getTrackId());
                    jobMapper.finish(job.getId(), "DONE", null, 1, null);
                    log.info("任务 {} 本地已收录，跳过抓取：{}", job.getId(), currentLabel);
                    return;
                }
            }

            // ② 同一张专辑的别的歌可能已经解析过了。同一歌手 + 同一专辑名，
            //    问 MusicBrainz 一百遍也是同一张 release，直接复用
            String releaseMbid = job.getAlbumName() == null || job.getAlbumName().isBlank()
                    ? null
                    : jobMapper.findDoneRelease(job.getArtistName(), job.getAlbumName());

            if (releaseMbid == null) {
                MbReleaseCandidateVO candidate = lookupService.findRelease(
                        job.getTitle(), job.getArtistName(), job.getDurationMs(), job.getAlbumName());
                releaseMbid = candidate == null ? null : candidate.getMbid();
            }

            if (releaseMbid == null) {
                // 不是错误，是常态：本地对不上的歌里相当一部分上游也没有。
                //
                // 两种原因分开说清楚，因为它们对用户的意义不同：
                //   ① 录音根本没找到 —— 这个名字 MusicBrainz 上没有
                //   ② 录音找到了、但不属于任何发行版 —— 近几年的中文独立发行里很常见，
                //      实测郑润泽《如果呢》就是（标题和艺人都精确命中，releases 为空）
                // ②其实「找到了但抓不了」，只报「找不到」会让人以为搜错了名字
                jobMapper.finish(job.getId(), "NOT_FOUND", null, 0,
                        "MusicBrainz 上没有可入库的专辑"
                                + "（这首歌查不到，或者它不属于任何发行版）");
                log.info("任务 {} 未找到：{}", job.getId(), currentLabel);
                return;
            }

            // 一张专辑里常常有好几首歌要入库。第二首起就不必再起子进程了，
            // 库里已经是同一份数据。省的是子进程 + 一次 get_release
            if (jobMapper.countDoneByRelease(releaseMbid) == 0) {
                String failure = runPipeline(releaseMbid, job.getId());
                if (failure != null) {
                    jobMapper.finish(job.getId(), "FAILED", releaseMbid, 0, truncate(failure, 900));
                    log.warn("任务 {} 抓取失败：{}", job.getId(), failure);
                    return;
                }
            }

            int rematched = rematch(job);
            jobMapper.finish(job.getId(), "DONE", releaseMbid, rematched, null);
            log.info("任务 {} 完成：{} → release {}（重对齐 {} 行，耗时 {}ms）",
                    job.getId(), currentLabel, releaseMbid,
                    rematched, System.currentTimeMillis() - startedAt);

        } catch (Exception e) {
            jobMapper.finish(job.getId(), "FAILED", null, 0, truncate(e.toString(), 900));
            log.warn("任务 {} 异常：{}", job.getId(), currentLabel, e);
        } finally {
            currentJobId = null;
            currentLabel = null;
        }
    }

    /**
     * 入库完成后回头捞人。
     *
     * 【为什么要回头】导入在前、入库在后：用户导歌单时这些歌本地还没有，
     * 对齐结果只能是 UNRESOLVED。专辑进库之后，同一批行必须重试一遍才可能对上，
     * 否则「入库」按钮点完页面上什么都不会变。
     *
     * 【捞的是全表，不只当前用户】——入库产物写进全库共享的音乐侧表，
     * 别人歌单里的同一首歌现在也能对上了，顺手一起解决不额外花时间。
     */
    private int rematch(IngestionJob job) {
        List<String> variants = KeywordVariants.of(job.getArtistName());
        if (variants.isEmpty()) {
            return 0;
        }

        List<RematchCandidateVO> rows = importMapper.selectRematchCandidates(
                KeywordVariants.at(variants, 0),
                KeywordVariants.at(variants, 1),
                KeywordVariants.at(variants, 2));

        int rematched = 0;
        for (RematchCandidateVO row : rows) {
            TrackMatchVO hit = importService.match(
                    row.getTitle(), ArtistText.primary(row.getArtists()), row.getDurationMs());
            if (hit == null) {
                continue;
            }
            userPlaylistMapper.updateMatch(
                    row.getImportId(), row.getExternalId(), "MATCHED", hit.getTrackId());
            rematched++;
        }
        return rematched;
    }

    // ============================================================
    // 子进程
    // ============================================================

    /** 起 Python 子进程抓一张 release。成功返回 null，失败返回原因 */
    private String runPipeline(String releaseMbid, Long jobId) throws IOException, InterruptedException {
        Path logFile = Paths.get(props.getLogDir()).resolve("job-" + jobId + ".log");
        Path parent = logFile.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }

        ProcessBuilder builder = new ProcessBuilder(
                props.getPython(), props.getScript(), releaseMbid);
        builder.directory(new File(props.getDataPipelineDir()));

        // 【必须合并 stderr】分成两个流而只读一个，另一个写满管道缓冲区时
        // 子进程会阻塞在 write 上，Java 这边 waitFor 到超时——一个假死
        builder.redirectErrorStream(true);
        builder.redirectOutput(ProcessBuilder.Redirect.appendTo(logFile.toFile()));

        // 脚本自己会把 stdout/stderr reconfigure 成 UTF-8（见 ingest_release.py 的说明），
        // 这儿再设一层，是给「脚本还没跑到那一行就报错」的情形兜底
        builder.environment().put("PYTHONIOENCODING", "utf-8");

        Process process = builder.start();

        try {
            if (!process.waitFor(props.getJobTimeoutSeconds(), TimeUnit.SECONDS)) {
                process.destroyForcibly();
                return "抓取超时（超过 " + props.getJobTimeoutSeconds() + " 秒）";
            }
        } catch (InterruptedException e) {
            // 停服 / 重启打断了 worker 线程。【必须在这儿杀子进程】——
            // Windows 下父进程退出不会终止子进程，它会变成孤儿继续往库里写；
            // 而下一次启动 requeueRunning 又把同一条任务打回队列重跑，
            // 于是两个进程写同一批表 → 锁等待超时 → 事务回滚 → 缓存留下死 id。
            process.destroyForcibly();
            Thread.currentThread().interrupt();
            throw e;
        }

        if (process.exitValue() != 0) {
            // 退出码是子进程判成败的唯一依据（见 ingest_release.py 的约定），
            // 具体原因在日志尾部
            return tail(logFile, 500);
        }
        return null;
    }

    /** 日志尾部。报错信息在最后几行，取尾部比取开头有用 */
    private static String tail(Path file, int maxChars) {
        try {
            String content = Files.readString(file, StandardCharsets.UTF_8).trim();
            if (content.isEmpty()) {
                return "子进程非 0 退出，但没有输出";
            }
            return content.length() <= maxChars
                    ? content
                    : content.substring(content.length() - maxChars);
        } catch (Exception e) {
            // 读日志失败不能把「抓取失败」变成另一个异常
            return "子进程非 0 退出，日志读取失败：" + e;
        }
    }

    /** error_message 是 varchar(1000)，留点余量 */
    private static String truncate(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.length() <= max ? s : s.substring(0, max);
    }
}
