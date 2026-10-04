package com.musicmind.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 追问消息的读取。**只读** —— 写是 agent-service 的事。
 *
 * 【UI 的数据源是这张表】不是 LangGraph 的 checkpoint ——
 * 那是库内部格式，换个版本就读不了。
 */
@Mapper
public interface AgentMessageMapper {

    @Select("""
            SELECT id, role, content, run_id, created_at
            FROM agent_message
            WHERE report_id = #{reportId}
            ORDER BY id
            """)
    List<Map<String, Object>> listByReport(@Param("reportId") Long reportId);

    /**
     * 一个会话的全部消息。**整段取回来**，不做增量 ——
     * 前端轮询时手里已经有前面的了，整段替换比算增量简单，也不会错位。
     *
     * content 是 JSON（{"answer":..., "recommendations":[...]}），
     * **原样透传不解析**，和 report_json 同一条规矩。
     */
    @Select("""
            SELECT id, role, content, run_id, created_at
            FROM agent_message
            WHERE conversation_id = #{conversationId}
            ORDER BY id
            """)
    List<Map<String, Object>> listByConversation(@Param("conversationId") Long conversationId);
}
