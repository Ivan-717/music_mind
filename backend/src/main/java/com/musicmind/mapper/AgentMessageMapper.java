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
}
