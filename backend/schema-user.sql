-- MusicMind 用户侧表结构（Phase 1）
-- 由 MySQL musicmind 库导出，生成日期 2026-09-22
-- 用途：换机器 / 重建用户体系 / 给面试官看建模
--
-- 归属：这几张表归 Spring Boot 写，Python Agent 只读。
--       音乐侧的表归 data-pipeline 写，Spring Boot 只读。
--
-- 前置：本文件依赖 data-pipeline/schema.sql 里的 `track` 表，
--       必须在它之后执行。顺序反了会直接报
--       "Failed to open the referenced table 'track'"。
--
-- 用法：
--   mysql -u root -p < data-pipeline/schema.sql
--   mysql -u root -p < backend/schema-user.sql
--
-- 注意：全是 CREATE TABLE IF NOT EXISTS，重复执行安全，不会删任何数据。
--
-- 本文件故意【不】关闭 FOREIGN_KEY_CHECKS：
-- 音乐侧 schema.sql 关掉它是因为要一次性建完整库；这里保持开启，
-- 缺前置表时能立刻炸出来，而不是静默建出 5 张外键悬空的表。

CREATE DATABASE IF NOT EXISTS `musicmind`
  DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `musicmind`;

CREATE TABLE IF NOT EXISTS `app_user` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `username` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '登录名',
  `password_hash` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'bcrypt 哈希，绝不存明文',
  `nickname` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '昵称',
  `avatar_url` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '头像地址',
  `email` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '邮箱',
  `status` tinyint unsigned NOT NULL DEFAULT '1' COMMENT '0=禁用 1=正常 2=注销',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_app_user_username` (`username`),
  UNIQUE KEY `uk_app_user_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户';

CREATE TABLE IF NOT EXISTS `favorite_track` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `user_id` bigint unsigned NOT NULL COMMENT '用户',
  `track_id` bigint unsigned NOT NULL COMMENT '歌曲',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '收藏时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_favorite_track_user_track` (`user_id`,`track_id`),
  KEY `idx_favorite_track_track_id` (`track_id`),
  CONSTRAINT `fk_favorite_track_user` FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_favorite_track_track` FOREIGN KEY (`track_id`) REFERENCES `track` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户收藏的歌曲';

CREATE TABLE IF NOT EXISTS `play_history` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `user_id` bigint unsigned NOT NULL COMMENT '用户',
  `track_id` bigint unsigned NOT NULL COMMENT '歌曲',
  `source` varchar(16) NOT NULL DEFAULT 'other' COMMENT '来源页：report/album/playlist/search/favorite/artist/chat/other（只有 report 是「推荐被采纳」的信号）',
  `played_ms` bigint unsigned NOT NULL DEFAULT '0' COMMENT '实际播放毫秒数（第一版恒 0：开始播时上报，拿不到最终时长）',
  `played_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '播放时刻',
  PRIMARY KEY (`id`),
  KEY `idx_play_history_user_time` (`user_id`,`played_at`),
  KEY `idx_play_history_track_id` (`track_id`),
  CONSTRAINT `fk_play_history_user` FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_play_history_track` FOREIGN KEY (`track_id`) REFERENCES `track` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='播放/试听记录（append-only，不更新。2026-10-08 起由试听上报写入 —— 推荐质量的在线信号）';

CREATE TABLE IF NOT EXISTS `playlist` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `user_id` bigint unsigned NOT NULL COMMENT '创建者',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '歌单名',
  `description` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '描述',
  `cover_url` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '封面，NULL 时前端用第一首的封面兜底',
  `is_public` tinyint(1) NOT NULL DEFAULT '0' COMMENT '0=私有 1=公开',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_playlist_user_id` (`user_id`),
  CONSTRAINT `fk_playlist_user` FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='歌单';

CREATE TABLE IF NOT EXISTS `playlist_track` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `playlist_id` bigint unsigned NOT NULL COMMENT '歌单',
  `track_id` bigint unsigned NOT NULL COMMENT '歌曲',
  `sort_order` int NOT NULL DEFAULT '0' COMMENT '歌单内排序，小在前',
  `added_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '加入时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_playlist_track` (`playlist_id`,`track_id`),
  KEY `idx_playlist_track_sort` (`playlist_id`,`sort_order`),
  KEY `idx_playlist_track_track_id` (`track_id`),
  CONSTRAINT `fk_playlist_track_playlist` FOREIGN KEY (`playlist_id`) REFERENCES `playlist` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_playlist_track_track` FOREIGN KEY (`track_id`) REFERENCES `track` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='歌单曲目';

CREATE TABLE IF NOT EXISTS `user_playlist_import` (
                                                      `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
                                                      `user_id` bigint unsigned NOT NULL COMMENT '用户',
                                                      `provider` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '平台：netease / qq',
    `external_playlist_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '平台上的歌单 id',
    `playlist_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '歌单名（平台上的）',
    `tags` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '歌单标签，逗号分隔（网易云 playlist.tags，用户建的歌单才有）',
    `source_url` varchar(768) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用户粘进来的原始链接',
    `track_count` int unsigned NOT NULL DEFAULT '0' COMMENT '最近一次抓到多少首',
    `last_imported_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最近一次导入时间',
    `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_import_user_playlist` (`user_id`,`provider`,`external_playlist_id`),
    CONSTRAINT `fk_import_user` FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户导入的外部歌单';

CREATE TABLE IF NOT EXISTS `user_playlist_track` (
                                                     `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
                                                     `import_id` bigint unsigned NOT NULL COMMENT '属于哪个导入的歌单',
                                                     `user_id` bigint unsigned NOT NULL COMMENT '用户（冗余，方便按用户直接查）',
                                                     `provider` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '平台',
    `external_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '平台上的歌曲 id',
    `position` int unsigned NOT NULL COMMENT '歌单里的顺序，从 1 开始',
    `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '歌名（外部原样）',
    `artists` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '歌手（外部原样，如「周杰伦 / 温岚」）',
    `album_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '专辑名（外部原样）',
    `release_year` smallint DEFAULT NULL COMMENT '发行年（网易云 album.publishTime，导入时补抓）——未入库的歌靠它进「年代」维度',
    `duration_ms` bigint unsigned DEFAULT NULL COMMENT '时长',
    `cover_url` varchar(768) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '平台封面 URL',
    `match_status` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING / MATCHED / UNRESOLVED',
    `matched_track_id` bigint unsigned DEFAULT NULL COMMENT '对齐到的本地曲目（未对齐为 NULL）',
    `matched_at` timestamp NULL DEFAULT NULL COMMENT '对齐时刻',
    `user_removed` tinyint(1) NOT NULL DEFAULT '0' COMMENT '用户手动剔除：1=不再显示，重新导入也不会复活（upsert 不碰这一列）',
    `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_upt_import_external` (`import_id`,`external_id`),
    KEY `idx_upt_import_visible` (`import_id`,`user_removed`,`position`),
    KEY `idx_upt_user_status` (`user_id`,`match_status`),
    CONSTRAINT `fk_upt_import`  FOREIGN KEY (`import_id`) REFERENCES `user_playlist_import` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT `fk_upt_user`    FOREIGN KEY (`user_id`)   REFERENCES `app_user` (`id`)              ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT `fk_upt_track`   FOREIGN KEY (`matched_track_id`) REFERENCES `track` (`id`)          ON DELETE SET NULL ON UPDATE RESTRICT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='导入歌单里的每一首（外部原始数据 + 对齐结果）';

CREATE TABLE IF NOT EXISTS `ingestion_job` (
    `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
    `user_id` bigint unsigned NOT NULL COMMENT '发起人。仅审计用——队列是全局共享的，不按用户隔离',
    `track_row_id` bigint unsigned NOT NULL COMMENT '触发的 user_playlist_track 行 id。故意不加外键：歌单删了，任务作为历史留着',
    `artist_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '外部歌手名（入库后重匹配用）',
    `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '外部歌名（重匹配用）',
    `album_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '外部专辑名（挑 release 时的加分信号）',
    `duration_ms` bigint unsigned DEFAULT NULL COMMENT '外部时长（挑录音时的校验信号）',
    `release_mbid` char(36) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '解析出的 MusicBrainz release MBID',
    `status` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'QUEUED' COMMENT 'QUEUED / RUNNING / DONE / FAILED / NOT_FOUND',
    `rematched_count` int unsigned NOT NULL DEFAULT '0' COMMENT '入完库重新对齐上的本地行数',
    `error_message` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '失败原因（子进程输出/日志尾部）',
    `started_at` timestamp NULL DEFAULT NULL COMMENT 'worker 领取时刻',
    `finished_at` timestamp NULL DEFAULT NULL,
    `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_job_status` (`status`,`id`),
    KEY `idx_job_track_row` (`track_row_id`,`status`),
    KEY `idx_job_release_mbid` (`release_mbid`,`status`),
    CONSTRAINT `fk_job_user` FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='按需入库队列（全局共享，单 worker 顺序消费）';
