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
  `played_ms` bigint unsigned NOT NULL DEFAULT '0' COMMENT '实际播放毫秒数',
  `played_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '播放时刻',
  PRIMARY KEY (`id`),
  KEY `idx_play_history_user_time` (`user_id`,`played_at`),
  KEY `idx_play_history_track_id` (`track_id`),
  CONSTRAINT `fk_play_history_user` FOREIGN KEY (`user_id`) REFERENCES `app_user` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_play_history_track` FOREIGN KEY (`track_id`) REFERENCES `track` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='播放记录（append-only，不更新）';

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
