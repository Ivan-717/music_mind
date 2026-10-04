-- MusicMind Agent 侧表结构
--
-- 归属（项目里第三条数据归属规则）：
--   音乐侧表（track/artist/album/…）    data-pipeline 写，这里只读
--   用户侧表（app_user/favorite_track/…）Spring Boot 写，这里只读
--   Agent 侧表（本文件）                 agent-service 写，Spring Boot 只读
--
-- 【为什么要写清这一条】现在有两套写权限已经很清楚了，加第三套如果不说，
-- 迟早出现「两边都写同一张表」，而那种 bug 表现为「数据偶尔不对」，极难定位。
--
-- 用法：
--   mysql -u root -p < data-pipeline/schema.sql      （先，音乐侧）
--   mysql -u root -p < backend/schema-user.sql       （再，用户侧）
--   mysql -u root -p < agent-service/schema-agent.sql（最后）
--
-- 全是 CREATE TABLE IF NOT EXISTS，重复执行安全。

USE `musicmind`;

-- ============================================================
-- 曲目音频特征
-- ============================================================

CREATE TABLE IF NOT EXISTS `track_audio_feature` (
  `track_id` bigint unsigned NOT NULL COMMENT '本地 track id。一首歌一行，重算覆盖',
  `arousal_measured` decimal(5,4) NOT NULL COMMENT '音乐能量 0-1。【只存实测值】RMS 0.5 + spectral centroid 0.3 + zcr 0.2。**推断值不许写进这张表** —— L5 靠「这列非空」判断某个断言能否用实测支撑',

  `tempo_bpm` decimal(6,1) DEFAULT NULL COMMENT '速度。【有倍频歧义，不参与 arousal】librosa 对无强鼓点的歌会把八分音符当拍',
  `rms` decimal(7,5) DEFAULT NULL COMMENT '响度均方根。最有效的能量分量',
  `spectral_centroid` decimal(8,1) DEFAULT NULL COMMENT '频谱质心 Hz，粗略等于「亮度」',
  `spectral_rolloff` decimal(8,1) DEFAULT NULL COMMENT '85% 能量以下的频率上界',
  `zero_crossing_rate` decimal(7,5) DEFAULT NULL COMMENT '过零率，和「嘈杂度」相关',
  `mode_major` tinyint(1) DEFAULT NULL COMMENT '大调=1 小调=0。**不可靠**（关系调歧义），只作原始记录',
  `mode_confidence` decimal(4,3) DEFAULT NULL COMMENT '调性判断的置信度。低于 0.6 就别解读 mode_major',

  `duration_s` decimal(5,1) DEFAULT NULL COMMENT '分析片段的长度，正常约 30 秒',
  `preview_url` varchar(768) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'iTunes 试听直链。④ 音频试听可直接复用。**可能过期**，播放端遇到 404 应重查而不是报错',
  `artist_verified` tinyint(1) NOT NULL DEFAULT '0' COMMENT '艺人名是否核对上了。iTunes 美国店存罗马字名（薛之谦=Joker Xue），对不上时只能按标题匹配，此时为 0',
  `analyzer_version` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '特征算法版本。换算法必须升版本，否则新旧口径混在一张表里',

  `analyzed_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`track_id`),
  KEY `idx_taf_arousal` (`arousal_measured`),
  CONSTRAINT `fk_taf_track` FOREIGN KEY (`track_id`) REFERENCES `track` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='曲目音频特征（agent-service 从 30 秒试听算出）';

-- ============================================================
-- 分析失败记录
-- ============================================================

CREATE TABLE IF NOT EXISTS `track_audio_analysis_fail` (
  `track_id` bigint unsigned NOT NULL,
  `reason` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '失败原因',
  `permanent` tinyint(1) NOT NULL DEFAULT '0' COMMENT '1=重试也没用（比如 iTunes 上根本没有这首），续跑时跳过；0=可能是网络抖动，下次重试',
  `attempts` int unsigned NOT NULL DEFAULT '1' COMMENT '试过几次。连续失败多次可以考虑人工看看',
  `last_attempt_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`track_id`),
  CONSTRAINT `fk_taaf_track` FOREIGN KEY (`track_id`) REFERENCES `track` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='音频分析失败的曲目。没有它，每次续跑都会把拿不到试听的歌重新问一遍';

-- ============================================================
-- 报告
-- ============================================================

CREATE TABLE IF NOT EXISTS `agent_report` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  -- 【必须 32，不是 16】'insufficient_data' 有 17 个字符 ——
  -- 第一版写成 varchar(16)，而同一行的注释里就列着这个值，插进去直接
  -- Data too long，而且报错发生在【生成完之后写库那一步】：
  -- 前面 40 秒的 LLM 开销全白费，任务标成 FAILED。
  -- 列宽按最长的那个值 + 余量定，不是按「看着够」
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'ok'
    COMMENT 'ok / degraded / insufficient_data',

  -- 【分析范围】这一份报告是基于哪批曲目生成的。
  --   all       = 收藏 + 全部导入歌单（旧报告也是这个语义，默认值正好）
  --   favorites = 只要收藏
  --   playlist  = 只要 scope_ref 指的那一张导入歌单
  -- 三列都写进报告而不是只写进 run：报告列表页直接查这张表（不 JOIN run），
  -- 而追问要按同样的范围重建 context —— 不重建的话，追问查出来的 facts
  -- 和报告里的数字对不上，而那种错没有任何东西会报警。
  `scope_kind` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'all'
    COMMENT 'all / favorites / playlist',
  -- 【故意不加外键】歌单被删掉时，历史报告必须留着。
  -- 代价是 scope_ref 可能悬空：读的时候要当「歌单已删除」处理，不能静默返回空集
  `scope_ref` bigint unsigned DEFAULT NULL
    COMMENT 'scope_kind=playlist 时是 user_playlist_import.id',
  -- 显示用。**存快照**，不从导入表 JOIN —— 歌单改名或删除后，
  -- 历史报告仍然要显示得出「这份是按哪张歌单生成的」
  `scope_label` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '全部',

  -- 【报告主体存 JSON 列，不拆表】schema 还会演化（Phase 7 要加维度），
  -- 拆成 claim 明细表的话每加一个字段都要迁移。库里有先例：album.secondary_types
  `report_json` json NOT NULL COMMENT '渲染后的完整报告',
  `facts_json` json DEFAULT NULL COMMENT '本轮的事实仓快照，追问时要用',
  `data_scope_json` json DEFAULT NULL COMMENT '规模与覆盖率，前端直接显示',

  `headline` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '标题，列表页用',
  `llm_provider` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `llm_model` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `prompt_version` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `tokens_in` int unsigned DEFAULT NULL,
  `tokens_out` int unsigned DEFAULT NULL,
  `latency_ms` int unsigned DEFAULT NULL,

  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_report_user` (`user_id`,`id`),
  CONSTRAINT `fk_report_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='音乐人格报告（agent-service 写，Spring Boot 只读）';

-- ============================================================
-- 运行队列（形状照抄 ingestion_job）
-- ============================================================

CREATE TABLE IF NOT EXISTS `agent_run` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `kind` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'report'
    COMMENT 'report / ask',
  `question` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'ask 模式的问题',
  `report_id` bigint unsigned DEFAULT NULL COMMENT 'ask 针对哪份报告；report 完成后回填',
  `conversation_id` bigint unsigned DEFAULT NULL COMMENT 'chat 属于哪个会话。和 report_id 互斥',
  `provider` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,

  -- 【这一趟要分析哪些曲目】子进程靠它重建 context。
  -- 队列项是短命的，所以这里不存 label —— 显示用的份在 agent_report 上
  `scope_kind` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'all'
    COMMENT 'all / favorites / playlist',
  `scope_ref` bigint unsigned DEFAULT NULL
    COMMENT 'scope_kind=playlist 时是 user_playlist_import.id',

  `status` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'QUEUED'
    COMMENT 'QUEUED / RUNNING / DONE / FAILED',
  `error_message` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `started_at` timestamp NULL DEFAULT NULL,
  `finished_at` timestamp NULL DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  KEY `idx_run_status` (`status`,`id`),
  KEY `idx_run_user` (`user_id`,`id`),
  CONSTRAINT `fk_run_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Agent 运行队列（单 worker 顺序消费）';

-- ============================================================
-- 对话（自由问答的会话）
-- ============================================================

CREATE TABLE IF NOT EXISTS `agent_conversation` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `user_id` bigint unsigned NOT NULL,
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '新的对话',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_conv_user` (`user_id`,`id`),
  CONSTRAINT `fk_conv_user` FOREIGN KEY (`user_id`)
    REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='自由问答的会话。和「针对某份报告的追问」是两条独立的线';

-- ============================================================
-- 消息（追问 + 对话共用一张表）
-- ============================================================

CREATE TABLE IF NOT EXISTS `agent_message` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  -- 【两列可空且互斥】
  --   追问：report_id = 某份报告，content 是纯文本
  --   对话：conversation_id = 某个会话，content 是 JSON
  --         {"answer": "...", "recommendations": [...]}
  -- 两种形状靠挂在哪一列上区分，读的时候按会话类型解析
  `report_id` bigint unsigned DEFAULT NULL,
  `conversation_id` bigint unsigned DEFAULT NULL,
  `run_id` bigint unsigned DEFAULT NULL,
  `role` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'user / assistant',
  `content` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_msg_report` (`report_id`,`id`),
  KEY `idx_msg_conv` (`conversation_id`,`id`),
  CONSTRAINT `fk_msg_report` FOREIGN KEY (`report_id`)
    REFERENCES `agent_report` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='追问和对话的消息。UI 的数据源是这张表 —— LangGraph 的 checkpoint 是库内部格式，不能当 UI 数据源';
