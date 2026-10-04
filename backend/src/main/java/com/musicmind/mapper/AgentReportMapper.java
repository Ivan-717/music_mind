package com.musicmind.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 报告的读取。**只读** —— 写是 agent-service 的事。
 *
 * 【这一层不做任何 JSON 解析】report_json 是 JSON 列，JDBC 取出来就是 String，
 * 原样传给前端。一旦这里出现 `report_json->>'$.dimensions'` 这种 SQL，
 * 报告结构一改就要两边同时改。
 */
@Mapper
public interface AgentReportMapper {

    @Select("""
            SELECT id, user_id, status, headline, data_scope_json,
                   report_json, llm_provider, llm_model, tokens_in, tokens_out,
                   latency_ms, created_at
            FROM agent_report
            WHERE id = #{id} AND user_id = #{userId}
            """)
    Map<String, Object> findOwned(@Param("id") Long id, @Param("userId") Long userId);

    /** 列表页不要正文 —— 一份报告的 report_json 有几十 KB，拉十份就是几 MB */
    @Select("""
            SELECT id, status, headline, llm_provider, llm_model, latency_ms, created_at
            FROM agent_report
            WHERE user_id = #{userId}
            ORDER BY id DESC
            LIMIT 50
            """)
    List<Map<String, Object>> listByUser(@Param("userId") Long userId);
}
