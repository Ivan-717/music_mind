package com.musicmind.mapper;

import com.musicmind.entity.AgentRun;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;
import java.util.Map;

/**
 * Agent 队列的读写。形状照 IngestionJobMapper —— 那套已经跑了几百条任务。
 *
 * 【状态由谁改】Java 只做三件事：建行（排队）、领走（claim）、把卡死的打回队列。
 * DONE / FAILED 和 error_message 是 python 子进程写的 —— 它才知道真实结果。
 */
@Mapper
public interface AgentRunMapper {

    /**
     * 排一条任务。status 默认 QUEUED，scope_kind 默认 all（建表时给的默认值）。
     *
     * 【scope_kind 必须 COALESCE】它是 NOT NULL DEFAULT 'all'，但**显式传 NULL
     * 会覆盖掉默认值**，MySQL 直接报 "Column 'scope_kind' cannot be null"。
     * 而那个错被全局处理器归成 DataIntegrityViolationException → 404
     * 「引用的资源不存在」—— 看起来像越权或者报告不存在，完全指不到真正的原因。
     * 实测：ask 那条路径漏设了 scope，整条追问挂掉。
     */
    @Insert("""
            INSERT INTO agent_run (user_id, kind, question, report_id, provider,
                                   scope_kind, scope_ref, conversation_id)
            VALUES (#{userId}, #{kind}, #{question}, #{reportId}, #{provider},
                    COALESCE(#{scopeKind}, 'all'), #{scopeRef}, #{conversationId})
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(AgentRun run);

    /**
     * 队列里的下一个。
     *
     * 【没有 FOR UPDATE】加锁要配事务，而这个事务只包一条 SELECT 的话，
     * 锁在语句结束就没了，等于没加。真正的互斥靠 claim() 的条件更新。
     */
    @Select("""
            SELECT id, user_id, kind, question, report_id, provider,
                   scope_kind, scope_ref, conversation_id, status,
                   error_message, started_at, finished_at, created_at
            FROM agent_run
            WHERE status = 'QUEUED'
            ORDER BY id
            LIMIT 1
            """)
    AgentRun selectNextQueued();

    /**
     * 领取。
     *
     * 【WHERE 必须带 status='QUEUED'】JDBC 默认 useAffectedRows=false，
     * UPDATE 返回的是「匹配行数」不是「改变行数」，光看返回值判断不了有没有真抢到。
     * 这个条件本身才是互斥：已经被领走的行匹配不到，返回 0。
     */
    @Update("""
            UPDATE agent_run SET status = 'RUNNING', started_at = NOW()
             WHERE id = #{id} AND status = 'QUEUED'
            """)
    int claim(@Param("id") Long id);

    /**
     * Java 侧的兜底收尾，**只在于进程根本没跑成时用**（启动失败 / 超时 / 被中断）。
     *
     * 正常情况下 DONE / FAILED 是 python 写的 —— 真实结果只有它知道。
     * 但子进程起不来时它没机会写，不兜底这条就永远停在 RUNNING，
     * 前面一直转圈，唯一的恢复路径是重启后端。
     *
     * WHERE 带 status='RUNNING'：只收尾自己领走的那条，不误伤。
     */
    @Update("""
            UPDATE agent_run SET status = 'FAILED', error_message = #{message}, finished_at = NOW()
             WHERE id = #{id} AND status = 'RUNNING'
            """)
    int finishFailed(@Param("id") Long id, @Param("message") String message);

    /** 启动时把上次异常退出留下的 RUNNING 打回 QUEUED。没有它，任务永远停在「生成中」 */
    @Update("UPDATE agent_run SET status = 'QUEUED', started_at = NULL WHERE status = 'RUNNING'")
    int requeueRunning();

    /**
     * 把挂了太久的 RUNNING 打回 QUEUED（运行期清扫，worker 每 60 秒跑一次）。
     *
     * requeueRunning 只在启动时执行一次，兜不住运行期：python 写状态那一步
     * 自己失败（MySQL 抖一下）时，那条就永远停在 RUNNING，用户只能重启后端。
     */
    @Update("""
            UPDATE agent_run SET status = 'QUEUED', started_at = NULL
             WHERE status = 'RUNNING'
               AND started_at < NOW() - INTERVAL #{seconds} SECOND
            """)
    int requeueStale(@Param("seconds") long seconds);

    @Select("SELECT COUNT(*) FROM agent_run WHERE status = 'QUEUED'")
    int countQueued();

    /** 一条任务，带归属校验 —— 查别人的必须查不到 */
    @Select("""
            SELECT id, user_id, kind, question, report_id, provider,
                   scope_kind, scope_ref, conversation_id, status,
                   error_message, started_at, finished_at, created_at
            FROM agent_run
            WHERE id = #{id} AND user_id = #{userId}
            """)
    AgentRun findOwned(@Param("id") Long id, @Param("userId") Long userId);

    /** 同一份报告有没有在排/在跑的追问（防连点） */
    @Select("""
            SELECT COUNT(*) FROM agent_run
            WHERE report_id = #{reportId} AND kind = 'ask' AND status IN ('QUEUED', 'RUNNING')
            """)
    int countActiveAsk(@Param("reportId") Long reportId);

    /** 同一个会话有没有在排/在跑的对话（防连点）。和 countActiveAsk 同一个道理 */
    @Select("""
            SELECT COUNT(*) FROM agent_run
            WHERE conversation_id = #{conversationId} AND kind = 'chat'
              AND status IN ('QUEUED', 'RUNNING')
            """)
    int countActiveChat(@Param("conversationId") Long conversationId);

    @Select("""
            SELECT id, kind, question, report_id, provider,
                   scope_kind, scope_ref, conversation_id, status,
                   error_message, started_at, finished_at, created_at
            FROM agent_run
            WHERE user_id = #{userId}
            ORDER BY id DESC
            LIMIT #{limit}
            """)
    List<AgentRun> recent(@Param("userId") Long userId, @Param("limit") int limit);
}
