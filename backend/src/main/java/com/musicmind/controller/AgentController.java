package com.musicmind.controller;

import com.musicmind.dto.AskRequest;
import com.musicmind.dto.AgentFetchRequest;
import com.musicmind.dto.ChatRequest;
import com.musicmind.security.CurrentUser;
import com.musicmind.service.AgentService;
import com.musicmind.service.IngestionService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 音乐人格报告 + 追问。
 *
 * 【权限不用额外配】SecurityConfig 只放行了 login / register，
 * 其余 anyRequest().authenticated()，这几个端点自动受 JWT 保护。
 *
 * 【返回 Map 而不是 VO】这一层刻意不定义报告的结构 ——
 * 报告 schema 由 agent-service 定义，Java 只是个搬运工。
 * 定义 VO 就等于把 schema 抄了一份，一改就要两边同时改。
 */
@RestController
@RequestMapping("/api/agent")
@RequiredArgsConstructor
public class AgentController {

    private final AgentService agentService;
    private final IngestionService ingestionService;

    /**
     * 排一次报告生成。
     *
     * 【202 而不是 200】一次报告实测 p50 28.7s / p95 33.2s，
     * 而前端 axios 默认 timeout 10 秒 —— 同步接口必然超时。
     * 这里是「已受理」，进度靠 GET /api/agent/runs/{id} 轮询。
     */
    @PostMapping("/report")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> requestReport(
            @RequestParam(defaultValue = "deepseek") String provider,
            @RequestParam(defaultValue = "all") String scopeKind,
            @RequestParam(required = false) Long scopeRef) {
        return agentService.requestReport(CurrentUser.id(), provider, scopeKind, scopeRef);
    }

    /** 对一份已生成的报告追问。同样 202 + 轮询 */
    @PostMapping("/ask")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> ask(@Valid @RequestBody AskRequest req) {
        return agentService.ask(CurrentUser.id(), req.getReportId(), req.getQuestion());
    }

    /** 排一轮对话。conversationId 留空就新开一个会话。同样 202 + 轮询 */
    @PostMapping("/chat")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> chat(@Valid @RequestBody ChatRequest req) {
        return agentService.chat(CurrentUser.id(), req.getMessage(), req.getConversationId());
    }

    /**
     * 把 Agent 提议的专辑抓进库。
     *
     * 【为什么走这里而不是 Python 直接排队】`ingestion_job` 归 Java 写，
     * 而且排队有归属校验要做。Python 只管「查上游、给候选」。
     *
     * 落点是「AI 帮你找的」那张歌单 —— 用户能在「我的歌单」页看到、
     * 试听、一键收藏，也能删。
     */
    @PostMapping("/fetch")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> fetch(@Valid @RequestBody AgentFetchRequest req) {
        return ingestionService.queueAgentFetch(CurrentUser.id(), req.getProposals());
    }

    /** 我的会话列表（不含消息） */
    @GetMapping("/conversations")
    public List<Map<String, Object>> conversations() {
        return agentService.listConversations(CurrentUser.id());
    }

    /** 一个会话的全部消息。刷新页面靠它读回历史 */
    @GetMapping("/conversations/{id}")
    public Map<String, Object> conversation(@PathVariable Long id) {
        return agentService.conversationDetail(CurrentUser.id(), id);
    }

    /** 轮询这个：run 状态 + 报告（好了的话）+ 追问消息 */
    @GetMapping("/runs/{id}")
    public Map<String, Object> run(@PathVariable Long id) {
        return agentService.runStatus(CurrentUser.id(), id);
    }

    /** 我的报告列表 */
    @GetMapping("/reports")
    public List<Map<String, Object>> reports() {
        return agentService.listReports(CurrentUser.id());
    }

    /** 一份报告的正文 + 追问历史。刷新页面读回上次结果用 */
    @GetMapping("/reports/{id}")
    public Map<String, Object> report(@PathVariable Long id) {
        return agentService.reportDetail(CurrentUser.id(), id);
    }

    /** 队列状态（全局共享，只读） */
    @GetMapping("/status")
    public Map<String, Object> status() {
        return agentService.status(CurrentUser.id());
    }

    /** 当前这条跑完即停 */
    @PostMapping("/stop")
    public Map<String, Object> stop() {
        return agentService.stop();
    }

    @PostMapping("/resume")
    public Map<String, Object> resume() {
        return agentService.resume();
    }

    /** 认领型。body: {"name": "守夜人"} */
    @PostMapping("/reports/{id}/type")
    public Map<String, Object> claimType(@PathVariable Long id,
                                         @RequestBody Map<String, String> body) {
        return agentService.claimType(CurrentUser.id(), id, body.get("name"));
    }
}
