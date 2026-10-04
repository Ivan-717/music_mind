package com.musicmind.mapper;

import com.musicmind.entity.AgentConversation;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 对话会话的读写。
 *
 * 【归属规则的那个例外又用了一次】`agent_conversation` 是 agent 侧表，
 * 归 agent-service 写。但「开会话」和「建 run 行」一样，**是「排队」这个动作本身** ——
 * 用户点发送的那一刻产生的，不是 Python 算出来的。所以和 agent_run 同一个待遇。
 *
 * 返回 Map 不定义 VO：和报告一样，这一层只搬运，不抄 schema。
 */
@Mapper
public interface AgentConversationMapper {

    /** 开一个会话。返回自增 id */
    @Insert("""
            INSERT INTO agent_conversation (user_id, title)
            VALUES (#{userId}, #{title})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(AgentConversation row);

    /** 归属校验。查别人的会话必须查不到 */
    @Select("""
            SELECT id, title, created_at
            FROM agent_conversation
            WHERE id = #{id} AND user_id = #{userId}
            """)
    Map<String, Object> findOwned(@Param("id") Long id, @Param("userId") Long userId);

    /** 我的会话列表（不含消息）。新的在前 */
    @Select("""
            SELECT c.id, c.title, c.created_at,
                   (SELECT COUNT(*) FROM agent_message m WHERE m.conversation_id = c.id) AS message_count
            FROM agent_conversation c
            WHERE c.user_id = #{userId}
            ORDER BY c.id DESC
            LIMIT 50
            """)
    List<Map<String, Object>> listByUser(@Param("userId") Long userId);
}
