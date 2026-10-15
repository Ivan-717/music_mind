package com.musicmind.service;

import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 正在被订阅的 run 进度通道。
 *
 * 【没人订阅是常态】大多数 run（报告/追问）没有前端开 SSE —— 查不到
 * emitter 就安静丢掉，这不是错误。写事件失败（客户端断了）也只摘牌。
 */
@Component
public class AgentEventRegistry {

    private final Map<Long, SseEmitter> emitters = new ConcurrentHashMap<>();

    /** 前端订阅时注册。超时要显式设 —— 默认值很短，一轮 chat 要 20-40 秒 */
    public SseEmitter register(Long runId) {
        SseEmitter emitter = new SseEmitter(5 * 60 * 1000L);
        emitters.put(runId, emitter);
        Runnable remove = () -> emitters.remove(runId, emitter);
        emitter.onCompletion(remove);
        emitter.onTimeout(remove);
        emitter.onError(e -> remove.run());
        // 【首帧必须立刻发】SseEmitter 在第一次 send 前不会下发响应头 ——
        // 客户端会一直挂着（实测 curl 5 秒零字节，验收脚本直接判连不上）。
        // hello 帧既解除阻塞，也让订阅方知道「连上了，进度马上来」
        try {
            emitter.send(SseEmitter.event().name("stage")
                    .data(Map.of("note", "已连上，等进度…")));
        } catch (Exception e) {
            emitters.remove(runId, emitter);
        }
        return emitter;
    }

    /** run 结束（AgentWorker 调）：把还在看的客户端正常关流，
     *  否则连接挂到 5 分钟超时才断。没人订阅就什么都不做。 */
    public void complete(Long runId) {
        SseEmitter emitter = emitters.remove(runId);
        if (emitter == null) return;
        try {
            emitter.complete();
        } catch (Exception ignored) {
        }
    }

    public void stage(Long runId, String note) {
        SseEmitter emitter = emitters.get(runId);
        if (emitter == null) return;
        try {
            emitter.send(SseEmitter.event().name("stage")
                    .data(Map.of("note", note)));
        } catch (Exception e) {
            emitters.remove(runId, emitter);   // 客户端断了，摘牌即可
        }
    }
}