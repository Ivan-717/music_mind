package com.musicmind.service;

import com.musicmind.config.AgentProperties;
import com.musicmind.entity.AgentRun;
import com.musicmind.exception.ApiException;
import com.musicmind.mapper.AgentMessageMapper;
import com.musicmind.mapper.AgentReportMapper;
import com.musicmind.mapper.AgentRunMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Agent 的排队与查询。真正干活的是 AgentWorker。
 *
 * 【这一层最要紧的约束：不解析报告的 JSON 内部结构】
 * agent_report / agent_run / agent_message 三张表归 agent-service 写
 * （见 schema-user.sql 头注释的第三条归属规则）。报告结构由那边定义，
 * 这里拿到什么原样透传给前端。
 *
 * 一旦这里出现 reportJson.get("dimensions") 这种代码，
 * 报告 schema 一改就要两边同时改 —— 而那种 bug 在生产上才现形。
 */
@Service
@RequiredArgsConstructor
public class AgentService {

    private static final int MAX_QUESTION_LEN = 500;

    private final AgentRunMapper runMapper;
    private final AgentReportMapper reportMapper;
    private final AgentMessageMapper messageMapper;
    private final AgentWorker worker;
    private final AgentProperties props;

    // ============================================================
    // 排队
    // ============================================================

    /** 排一次报告生成。返回新 run 的 id */
    public Map<String, Object> requestReport(Long userId, String provider) {
        AgentRun run = new AgentRun();
        run.setUserId(userId);
        run.setKind("report");
        run.setProvider(normalizeProvider(provider));
        runMapper.insert(run);

        return Map.of("runId", run.getId(), "estimateSeconds", ESTIMATE_SECONDS);
    }

    /** 对一份已生成的报告追问 */
    public Map<String, Object> ask(Long userId, Long reportId, String question) {
        if (question == null || question.isBlank()) {
            throw new ApiException(400, "问题不能为空");
        }
        if (question.length() > MAX_QUESTION_LEN) {
            throw new ApiException(400, "问题太长了");
        }

        // 归属校验在 AgentReportMapper 里做（查不到就 404），
        // 这里先确认报告存在且属于本人
        if (reportMapper.findOwned(reportId, userId) == null) {
            throw new ApiException(404, "报告不存在");
        }

        // 防连点：同一份报告已经有在排/在跑的追问时不再排。
        // 追问是「顺手问一句」，连点两次多半是以为没生效
        if (runMapper.countActiveAsk(reportId) > 0) {
            throw new ApiException(409, "这份报告已经有一个追问在排队了，等它出来再问");
        }

        AgentRun run = new AgentRun();
        run.setUserId(userId);
        run.setKind("ask");
        run.setReportId(reportId);
        run.setQuestion(question.trim());
        run.setProvider(normalizeProvider(null));
        runMapper.insert(run);

        return Map.of("runId", run.getId());
    }

    // ============================================================
    // 查询
    // ============================================================

    /**
     * 一条 run 的当前状态 + 报告（好了的话）+ 追问消息。
     *
     * 【前端轮询就调这个】一次报告 30 秒，axios 默认 timeout 10 秒，
     * 同步接口必然超时 —— 所以是「排队 + 轮询」。
     */
    public Map<String, Object> runStatus(Long userId, Long runId) {
        AgentRun run = runMapper.findOwned(runId, userId);
        if (run == null) {
            throw new ApiException(404, "任务不存在");
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("run", runView(run));

        if (run.getReportId() != null) {
            Map<String, Object> report = reportMapper.findOwned(run.getReportId(), userId);
            if (report != null) {
                // 【原样透传，不解析】report_json 是 JSON 列，MyBatis 取出来是 String，
                // 前端自己 JSON.parse。Java 这边只负责搬运
                body.put("report", report);
                body.put("messages", messageMapper.listByReport(run.getReportId()));
            }
        }
        return body;
    }

    /** 我的报告列表（不含正文，只给标题和时间） */
    public List<Map<String, Object>> listReports(Long userId) {
        return reportMapper.listByUser(userId);
    }

    /**
     * 按报告 id 取正文 + 追问历史。
     *
     * 【为什么需要它】/runs/{id} 要的是「运行 id」，而刷新页面时手里只有报告 id ——
     * 光有列表读不回正文。「进程重启后历史还在」这条验收标准靠的就是这个接口。
     *
     * 和 runStatus 一样【原样透传 report_json 不解析】。
     */
    public Map<String, Object> reportDetail(Long userId, Long reportId) {
        Map<String, Object> report = reportMapper.findOwned(reportId, userId);
        if (report == null) {
            // 不属于本人时也走这里 —— 越权和不存在的返回完全一样，
            // 否则「猜 id 试出别人有几份报告」就成了信息泄露
            throw new ApiException(404, "报告不存在");
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("report", report);
        body.put("messages", messageMapper.listByReport(reportId));
        return body;
    }

    /** 队列状态。前端画进度面板用 */
    public Map<String, Object> status(Long userId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("paused", worker.isPaused());
        body.put("queueCount", runMapper.countQueued());
        body.put("currentRunId", worker.getCurrentRunId());
        body.put("currentLabel", worker.getCurrentLabel());

        List<Map<String, Object>> runs = new ArrayList<>();
        for (AgentRun run : runMapper.recent(userId, props.getRecentRuns())) {
            runs.add(runView(run));
        }
        body.put("recentRuns", runs);
        return body;
    }

    // 【停止/恢复只需要队列层面的状态，不查某个人的历史任务】
    // 原来这里写成 status(null)，recent(null, ...) 会返回空 —— 不算崩，
    // 但语义是错的：这两个接口和「谁」无关
    public Map<String, Object> stop() {
        worker.pause();
        return queueView();
    }

    public Map<String, Object> resume() {
        worker.resume();
        return queueView();
    }

    private Map<String, Object> queueView() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("paused", worker.isPaused());
        body.put("queueCount", runMapper.countQueued());
        body.put("currentRunId", worker.getCurrentRunId());
        body.put("currentLabel", worker.getCurrentLabel());
        return body;
    }

    // ============================================================

    /** run 的展示视图。**不含 user_id** —— 队列全局共享，暴露别人的 id 没意义 */
    private static Map<String, Object> runView(AgentRun run) {
        Map<String, Object> view = new HashMap<>();
        view.put("id", run.getId());
        view.put("kind", run.getKind());
        view.put("question", run.getQuestion());
        view.put("reportId", run.getReportId());
        view.put("provider", run.getProvider());
        view.put("status", run.getStatus());
        view.put("errorMessage", run.getErrorMessage());
        view.put("createdAt", run.getCreatedAt());
        view.put("finishedAt", run.getFinishedAt());
        return view;
    }

    private static String normalizeProvider(String provider) {
        return "qwen".equals(provider) ? "qwen" : "deepseek";
    }

    /** 一次报告的估算耗时。实测 p50 28.7s / p95 33.2s，取 40 秒给用户一个数量级 */
    private static final int ESTIMATE_SECONDS = 40;
}
