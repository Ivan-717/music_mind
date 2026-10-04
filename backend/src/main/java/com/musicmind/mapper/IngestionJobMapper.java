package com.musicmind.mapper;

import com.musicmind.entity.IngestionJob;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * 按需入库队列（ingestion_job）的读写。
 *
 * 状态机：QUEUED → RUNNING → DONE | FAILED | NOT_FOUND
 * 启动时 RUNNING → QUEUED（进程崩了，任务不能烂在半路）；
 * FAILED / NOT_FOUND 允许重排——上游数据会变，上次找不到不代表这次找不到。
 */
@Mapper
public interface IngestionJobMapper {

    @Insert("""
            INSERT INTO ingestion_job
                (user_id, track_row_id, artist_name, title, album_name, duration_ms,
                 release_mbid, status)
            VALUES
                (#{userId}, #{trackRowId}, #{artistName}, #{title}, #{albumName}, #{durationMs},
                 #{releaseMbid}, 'QUEUED')
            """)
    @Options(useGeneratedKeys = true, keyProperty = "id")
    /**
     * 排一条任务。
     *
     * 【release_mbid 必须在这里】它原本是 worker 解析完之后才写的**输出**列，
     * 所以最初的 INSERT 里没有它 —— 于是 agent 发起的抓取（排队时就知道 mbid）
     * setReleaseMbid 的值被【静默丢掉】，worker 只好回去搜录音，而拿专辑名搜录音
     * 必然找不到。5 张里 3 张 NOT_FOUND，错误信息还指不到真正的原因。
     */
    int insert(IngestionJob job);

    /**
     * 队列里的下一个。
     *
     * 【没有 FOR UPDATE】：加锁要配事务，而这个事务只包一条 SELECT 的话，
     * 锁在语句结束就没了，等于没加。真正的互斥靠下面的 claim()。
     */
    @Select("""
            SELECT id, user_id, track_row_id, artist_name, title, album_name, duration_ms,
                   release_mbid, status, rematched_count, error_message,
                   started_at, finished_at, created_at, updated_at
            FROM ingestion_job
            WHERE status = 'QUEUED'
            ORDER BY id
            LIMIT 1
            """)
    IngestionJob selectNextQueued();

    /**
     * 领取一条任务。
     *
     * 【WHERE 里必须带 status = 'QUEUED'】——JDBC 默认 useAffectedRows=false，
     * UPDATE 返回的是「匹配到的行数」而不是「真正改变的行数」，
     * 光看返回值判断不了有没有真的抢到。这个条件本身才是互斥：
     * 已经被别人领走的行匹配不到，返回 0。
     */
    @Update("""
            UPDATE ingestion_job
               SET status = 'RUNNING', started_at = NOW(), error_message = NULL
             WHERE id = #{id} AND status = 'QUEUED'
            """)
    int claim(@Param("id") Long id);

    /** 收尾。status 只传 DONE / FAILED / NOT_FOUND */
    @Update("""
            UPDATE ingestion_job
               SET status = #{status},
                   release_mbid = #{releaseMbid},
                   rematched_count = #{rematchedCount},
                   error_message = #{errorMessage},
                   finished_at = NOW()
             WHERE id = #{id}
            """)
    int finish(@Param("id") Long id,
               @Param("status") String status,
               @Param("releaseMbid") String releaseMbid,
               @Param("rematchedCount") int rematchedCount,
               @Param("errorMessage") String errorMessage);

    /** 启动时把上次异常退出留下的 RUNNING 打回 QUEUED。没有它，任务会永远卡在「抓取中」 */
    @Update("UPDATE ingestion_job SET status = 'QUEUED', started_at = NULL WHERE status = 'RUNNING'")
    int requeueRunning();

    /**
     * 把挂了太久的 RUNNING 打回 QUEUED（运行期清扫，worker 每 60 秒跑一次）。
     *
     * requeueRunning 只在启动时执行一次，兜不住运行期的情况：
     * finish() 自己失败（MySQL 抖一下）时那条任务会永远停在 RUNNING，
     * 而 countActiveByTrackRow 又把同一行的重排挡掉，用户只能重启后端。
     */
    @Update("""
            UPDATE ingestion_job
               SET status = 'QUEUED', started_at = NULL
             WHERE status = 'RUNNING'
               AND started_at < NOW() - INTERVAL #{seconds} SECOND
            """)
    int requeueStale(@Param("seconds") long seconds);

    @Select("SELECT COUNT(*) FROM ingestion_job WHERE status = 'QUEUED'")
    int countQueued();

    /** 这一行还有没有在排/在跑的任务。防止同一首连点两次排两条 */
    @Select("""
            SELECT COUNT(*) FROM ingestion_job
            WHERE track_row_id = #{trackRowId} AND status IN ('QUEUED', 'RUNNING')
            """)
    int countActiveByTrackRow(@Param("trackRowId") Long trackRowId);

    /**
     * 同一个歌手的同一首歌有没有在排/在跑。
     *
     * 跨歌单去重：不同歌单里同一首歌是两行 user_playlist_track，
     * 只按 track_row_id 去重的话会重复抓同一张专辑两次。
     * 空格要归一——还是「G.E.M.邓紫棋」对「G.E.M. 鄧紫棋」那个老问题。
     */
    @Select("""
            SELECT COUNT(*) FROM ingestion_job
            WHERE status IN ('QUEUED', 'RUNNING')
              AND REPLACE(artist_name, ' ', '') = REPLACE(#{artistName}, ' ', '')
              AND REPLACE(title, ' ', '') = REPLACE(#{title}, ' ', '')
            """)
    int countActiveByArtistTitle(@Param("artistName") String artistName,
                                 @Param("title") String title);

    /**
     * 同一歌手 + 同一专辑名，之前解析成功过的 release。
     *
     * 【这是省时间的关键一步】歌单里一张专辑常常有好几首（实测薛之谦一张专辑
     * 在同一个歌单里有 10 首），而 726 个排队任务其实只对应 496 个「歌手+专辑」组合。
     * 第一首解析完，后面那些没必要再花 2 秒问一次 MusicBrainz——
     * 同样的查询必然得到同样的结果。
     *
     * album_name 为空时【不要调这个方法】，调用方先判空：
     * 专辑名是选 release 的重要信号，空值配不出唯一结果。
     */
    @Select("""
            SELECT release_mbid FROM ingestion_job
            WHERE status = 'DONE' AND release_mbid IS NOT NULL
              AND artist_name = #{artistName} AND album_name = #{albumName}
            ORDER BY id DESC LIMIT 1
            """)
    String findDoneRelease(@Param("artistName") String artistName,
                           @Param("albumName") String albumName);

    /**
     * 这张 release 有没有成功入库过。
     *
     * 一张专辑里常常有好几首歌都要入库，第二首起就不必再起子进程了——
     * 库里的数据是一样的。省的是子进程 + 一次 get_release，累计很可观。
     */
    @Select("""
            SELECT COUNT(*) FROM ingestion_job
            WHERE release_mbid = #{releaseMbid} AND status = 'DONE'
            """)
    int countDoneByRelease(@Param("releaseMbid") String releaseMbid);

    /** 队列里所有还活着的任务对应的曲目行 id。前端拿它把行标成「抓取中」 */
    @Select("SELECT track_row_id FROM ingestion_job WHERE status IN ('QUEUED', 'RUNNING')")
    List<Long> selectActiveTrackRowIds();

    @Select("""
            SELECT id, track_row_id, artist_name, title, album_name, release_mbid, status,
                   rematched_count, error_message, started_at, finished_at, created_at
            FROM ingestion_job
            ORDER BY id DESC
            LIMIT #{limit}
            """)
    List<IngestionJob> recent(@Param("limit") int limit);
}
