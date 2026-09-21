-- MusicMind 数据库结构
-- 由 MySQL musicmind 库导出，生成日期 2026-09-21
-- 用途：换机器 / 重建知识库 / 给面试官看建模
--
-- 用法：
--   mysql -u root -p < schema.sql
--
-- 注意：全是 CREATE TABLE IF NOT EXISTS，重复执行安全，不会删任何数据。

CREATE DATABASE IF NOT EXISTS `musicmind`
  DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `musicmind`;

SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;

CREATE TABLE IF NOT EXISTS `album` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `musicbrainz_id` char(36) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'MusicBrainz Release Group MBID',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '专辑名称',
  `release_date` date DEFAULT NULL COMMENT '首次发行日期',
  `primary_type` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '专辑主要类型',
  `secondary_types` json DEFAULT NULL COMMENT '专辑其他类型',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_album_musicbrainz_id` (`musicbrainz_id`),
  KEY `idx_album_name` (`name`),
  KEY `idx_album_release_date` (`release_date`)
) ENGINE=InnoDB AUTO_INCREMENT=475 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='音乐专辑';

CREATE TABLE IF NOT EXISTS `artist` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `musicbrainz_id` char(36) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'MusicBrainz Artist MBID',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '艺术家名称',
  `sort_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '用于排序的名称',
  `disambiguation` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '消歧说明',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_artist_musicbrainz_id` (`musicbrainz_id`),
  KEY `idx_artist_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=665 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='音乐艺术家';

CREATE TABLE IF NOT EXISTS `album_artist` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `album_id` bigint unsigned NOT NULL COMMENT '专辑 ID',
  `artist_id` bigint unsigned NOT NULL COMMENT '艺术家 ID',
  `credited_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '该专辑中的署名名称',
  `join_phrase` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '艺术家之间的连接词',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_album_artist` (`album_id`,`artist_id`),
  KEY `idx_album_artist_album_id` (`album_id`),
  KEY `idx_album_artist_artist_id` (`artist_id`),
  CONSTRAINT `fk_album_artist_album` FOREIGN KEY (`album_id`) REFERENCES `album` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_album_artist_artist` FOREIGN KEY (`artist_id`) REFERENCES `artist` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=1172 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='专辑艺术家关联';

CREATE TABLE IF NOT EXISTS `genre` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '风格名称（MusicBrainz genre）',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_genre_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='音乐风格字典';

CREATE TABLE IF NOT EXISTS `album_genre` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `album_id` bigint unsigned NOT NULL COMMENT '专辑 ID',
  `genre_id` bigint unsigned NOT NULL COMMENT '风格 ID',
  `weight` int NOT NULL DEFAULT '0' COMMENT 'MusicBrainz 标签票数，越大越有代表性',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_album_genre` (`album_id`,`genre_id`),
  KEY `idx_album_genre_album_id` (`album_id`),
  KEY `idx_album_genre_genre_id` (`genre_id`),
  CONSTRAINT `fk_album_genre_album` FOREIGN KEY (`album_id`) REFERENCES `album` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_album_genre_genre` FOREIGN KEY (`genre_id`) REFERENCES `genre` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='专辑风格关联';

CREATE TABLE IF NOT EXISTS `artist_alias` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `artist_id` bigint unsigned NOT NULL COMMENT '所属艺术家',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '艺术家别名',
  `locale` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '' COMMENT '语言/地区',
  `is_primary` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否为主要别名',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_artist_alias` (`artist_id`,`name`,`locale`),
  KEY `idx_artist_alias_artist_id` (`artist_id`),
  KEY `idx_artist_alias_name` (`name`),
  CONSTRAINT `fk_artist_alias_artist` FOREIGN KEY (`artist_id`) REFERENCES `artist` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=1027 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='艺术家别名';

CREATE TABLE IF NOT EXISTS `artist_genre` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `artist_id` bigint unsigned NOT NULL COMMENT '艺术家 ID',
  `genre_id` bigint unsigned NOT NULL COMMENT '风格 ID',
  `weight` int NOT NULL DEFAULT '0' COMMENT 'MusicBrainz 标签票数，越大越有代表性',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_artist_genre` (`artist_id`,`genre_id`),
  KEY `idx_artist_genre_artist_id` (`artist_id`),
  KEY `idx_artist_genre_genre_id` (`genre_id`),
  CONSTRAINT `fk_artist_genre_artist` FOREIGN KEY (`artist_id`) REFERENCES `artist` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_artist_genre_genre` FOREIGN KEY (`genre_id`) REFERENCES `genre` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='艺术家风格关联';

CREATE TABLE IF NOT EXISTS `music_release` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `musicbrainz_id` char(36) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'MusicBrainz Release MBID',
  `album_id` bigint unsigned NOT NULL COMMENT '所属专辑',
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '发行版本名称',
  `release_date` date DEFAULT NULL COMMENT '发行日期',
  `country` char(2) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '发行地区 ISO 代码',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '发行状态',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_music_release_musicbrainz_id` (`musicbrainz_id`),
  KEY `idx_music_release_album_id` (`album_id`),
  KEY `idx_music_release_title` (`title`),
  KEY `idx_music_release_date` (`release_date`),
  CONSTRAINT `fk_music_release_album` FOREIGN KEY (`album_id`) REFERENCES `album` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=1133 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='音乐发行版本';

CREATE TABLE IF NOT EXISTS `track` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `musicbrainz_recording_id` char(36) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'MusicBrainz Recording MBID',
  `name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '歌曲名称',
  `duration_ms` bigint unsigned DEFAULT NULL COMMENT '歌曲时长，单位毫秒',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_track_musicbrainz_recording_id` (`musicbrainz_recording_id`),
  KEY `idx_track_name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=10221 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='歌曲录音实体';

CREATE TABLE IF NOT EXISTS `release_track` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `release_id` bigint unsigned NOT NULL COMMENT '发行版本 ID',
  `track_id` bigint unsigned NOT NULL COMMENT '歌曲 ID',
  `track_number` int unsigned NOT NULL COMMENT '该发行版本中的曲目序号',
  `disc_number` int unsigned NOT NULL DEFAULT '1' COMMENT '碟片序号',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_release_track` (`release_id`,`disc_number`,`track_number`),
  KEY `idx_release_track_release_id` (`release_id`),
  KEY `idx_release_track_track_id` (`track_id`),
  CONSTRAINT `fk_release_track_release` FOREIGN KEY (`release_id`) REFERENCES `music_release` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_release_track_track` FOREIGN KEY (`track_id`) REFERENCES `track` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=12274 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='发行版本与歌曲关联';

CREATE TABLE IF NOT EXISTS `track_artist` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'MusicMind 内部主键',
  `track_id` bigint unsigned NOT NULL COMMENT '歌曲 ID',
  `artist_id` bigint unsigned NOT NULL COMMENT '艺术家 ID',
  `credited_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '该歌曲中的署名名称',
  `join_phrase` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '艺术家之间的连接词',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_track_artist` (`track_id`,`artist_id`),
  KEY `idx_track_artist_track_id` (`track_id`),
  KEY `idx_track_artist_artist_id` (`artist_id`),
  CONSTRAINT `fk_track_artist_artist` FOREIGN KEY (`artist_id`) REFERENCES `artist` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT,
  CONSTRAINT `fk_track_artist_track` FOREIGN KEY (`track_id`) REFERENCES `track` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=12512 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='歌曲艺术家关联';

SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
