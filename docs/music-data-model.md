# MusicMind 音乐数据模型 v2.0

> 本文档记录 MusicMind 的核心音乐领域模型与实际 MySQL Schema。
>
> 该模型将作为后续 MySQL 数据库设计、音乐数据导入、RAG 知识库、Agent Tool 设计的基础。

**版本：v2.0**

**相对 v1.0 的核心变化：**

1. 明确 Album = MusicBrainz **Release Group**，新增 **Release**（具体发行版本）实体
2. Track **不再直接属于 Album**，正确链路为 `Album → Release → ReleaseTrack → Track`
3. Album / Track 与 Artist 均为 **N:M**，通过 `album_artist` / `track_artist` 中间表
4. MusicBrainz 作为外部数据来源，通过 Data Adapter → Repository 写入 MySQL
5. 用户系统整体推迟到第二阶段
6. 明确 MySQL / Qdrant / Agent 三层职责

> **文档约定**
>
> 每张表分两部分：
> - **已实现字段** —— 当前 `musicmind` 库中真实存在的列
> - **待补字段** —— v2.0 设计中有、但尚未加入数据库的列（多为 MusicMind 自有的标注数据，不来自 MusicBrainz）

---

# 一、系统定位

MusicMind 是一个 AI 音乐助手系统。

整体架构：

```text
             User
              |
              |
            Agent
              |
      -----------------
      |               |
    MySQL          Qdrant
      |               |
结构化事实       语义知识
```

职责划分：

| 模块 | 职责 |
|------|------|
| MySQL | 音乐实体和关系数据（结构化事实） |
| Qdrant | 音乐语义向量（语义知识） |
| Agent | 理解需求、调用工具、生成答案 |

---

# 二、核心数据来源

第一阶段的数据链路：

```text
MusicBrainz
      |
      |
Data Adapter
      |
      |
Repository
      |
      |
   MySQL
```

MusicBrainz 负责提供：

- Artist
- Release Group
- Release
- Recording
- Track
- Artist Credit

MusicMind 负责扩展：

- Genre
- Mood
- Scene
- Language
- Region
- 用户数据

---

# 三、核心音乐实体

第一阶段实现的核心实体：

```text
Artist
ArtistAlias
Album
AlbumArtist
Release (music_release)
ReleaseTrack
Track
TrackArtist
```

---

# 四、Artist

音乐艺术家。

例如：

```text
周杰伦
林俊杰
陈奕迅
五月天
```

## 已实现字段

```text
artist
--------------------------------
id                  bigint unsigned PK
musicbrainz_id      char(36) UNIQUE   MusicBrainz Artist MBID
name                varchar(255)      艺术家名称
sort_name           varchar(255)      排序用名称
disambiguation      varchar(255)      消歧说明
```

索引：

```text
UNIQUE uk_artist_musicbrainz_id (musicbrainz_id)
INDEX  idx_artist_name (name)
```

`musicbrainz_id` 用于关联外部音乐知识，例如：

```text
a223958d-5c56...
```

## 待补字段

```text
description     艺术家介绍
avatar          头像
country         国家
region_id       关联 region 表
debut_date      出道日期
created_at
updated_at
```

---

# 五、ArtistAlias

艺术家别名 / 译名。

例如：

```text
周杰伦 → Jay Chou / ジェイ・チョウ
```

单独成表（而非 Artist 上的一个字段），因为一个艺术家有多个别名。

## 已实现字段

```text
artist_alias
--------------------------------
id                  bigint unsigned PK
artist_id           bigint unsigned FK → artist.id
name                varchar(255)      别名
locale              varchar(32)       语言/地区，如 zh_CN、en
is_primary          tinyint(1)        是否为主要别名
```

索引：

```text
INDEX idx_artist_alias_artist_id (artist_id)
INDEX idx_artist_alias_name (name)
FOREIGN KEY fk_artist_alias_artist → artist(id) ON DELETE CASCADE
```

> **注意**：当前没有为 `artist_alias` 建立唯一约束。重复导入同一个艺术家时会插入重复别名，`upsert` 需要改成幂等逻辑（见文末「待处理问题」）。

---

# 六、Album

Album 对应 MusicBrainz **Release Group**，表示一张音乐作品集合。

例如：

```text
《范特西》
《七里香》
《她说》
```

## 已实现字段

```text
album
--------------------------------
id                  bigint unsigned PK
musicbrainz_id      char(36) UNIQUE   MusicBrainz Release Group MBID
name                varchar(255)      专辑名称
release_date        date              首次发行日期
primary_type        varchar(32)       专辑主要类型
secondary_types     json              专辑次要类型（多值）
```

索引：

```text
UNIQUE uk_album_musicbrainz_id (musicbrainz_id)
INDEX  idx_album_name (name)
INDEX  idx_album_release_date (release_date)
```

## 待补字段

```text
description     专辑介绍
cover_url       封面
created_at
updated_at
```

## 关系

**Album 与 Artist 是 N:M**，通过 `album_artist` 关联（合辑、合作专辑、`周杰伦 & 方文山` 这类场景）。

```text
Album N ─── M Artist
          ↓
      AlbumArtist
```

---

# 七、AlbumArtist

专辑与艺术家的多对多关系。

## 已实现字段

```text
album_artist
--------------------------------
id                  bigint unsigned PK
album_id            bigint unsigned FK → album.id
artist_id           bigint unsigned FK → artist.id
credited_name       varchar(255)      在该专辑中的署名
join_phrase         varchar(255)      艺术家之间的连接词，如 "&"、"feat."
```

索引：

```text
UNIQUE uk_album_artist (album_id, artist_id)
INDEX  idx_album_artist_album_id (album_id)
INDEX  idx_album_artist_artist_id (artist_id)
FOREIGN KEY fk_album_artist_album  → album(id)  ON DELETE CASCADE
FOREIGN KEY fk_album_artist_artist → artist(id) ON DELETE CASCADE
```

---

# 八、Release

Release 表示具体发行版本。

同一个 Album 可以有多个 Release，例如《范特西》：

```text
Album:
    范特西

Release:
    台湾 CD 版      2001-09-20
    日本版
    数字版
```

## 已实现字段

```text
music_release
--------------------------------
id                  bigint unsigned PK
musicbrainz_id      char(36) UNIQUE   MusicBrainz Release MBID
album_id            bigint unsigned FK → album.id
title               varchar(255)      发行版本名称
release_date        date              发行日期
country             char(2)           发行地区 ISO 国家码
status              varchar(32)       发行状态
```

索引：

```text
UNIQUE uk_music_release_musicbrainz_id (musicbrainz_id)
INDEX  idx_music_release_album_id (album_id)
INDEX  idx_music_release_title (title)
INDEX  idx_music_release_date (release_date)
FOREIGN KEY fk_music_release_album → album(id) ON DELETE CASCADE
```

> 表名用 `music_release` 而非 `release`，避免与 MySQL 关键字混淆。

## 待补字段

```text
created_at
updated_at
```

## 关系

```text
Album 1 ─── N Release
```

---

# 九、ReleaseTrack

发行版本中的歌曲列表。

例如《范特西》：

```text
1  愛在西元前
2  爸 我回來了
3  簡單愛
...
10 安靜
```

## 已实现字段

```text
release_track
--------------------------------
id                  bigint unsigned PK
release_id          bigint unsigned FK → music_release.id
track_id            bigint unsigned FK → track.id
track_number        int unsigned      该发行版本中的曲目序号
disc_number         int unsigned      唱片编号，默认 1
```

索引：

```text
UNIQUE uk_release_track (release_id, track_id)
INDEX  idx_release_track_release_id (release_id)
INDEX  idx_release_track_track_id (track_id)
FOREIGN KEY fk_release_track_release → music_release(id) ON DELETE CASCADE
FOREIGN KEY fk_release_track_track   → track(id)         ON DELETE CASCADE
```

> **注意**：唯一键是 `(release_id, track_id)`，意味着同一首歌在同一发行版本中只能出现一次。双 CD 版本中同一首歌重复出现（如 Bonus Disc）会冲突。

## 待补字段

```text
created_at
```

---

# 十、Track

音乐作品。

例如：

```text
愛在西元前
晴天
夜曲
```

## 已实现字段

```text
track
--------------------------------
id                          bigint unsigned PK
musicbrainz_recording_id    char(36) UNIQUE   MusicBrainz Recording MBID
name                        varchar(255)      歌曲名称
duration_ms                 bigint unsigned   时长（毫秒）
```

索引：

```text
UNIQUE uk_track_musicbrainz_recording_id (musicbrainz_recording_id)
INDEX  idx_track_name (name)
```

## 待补字段

```text
description     歌曲介绍
energy          音乐能量等级，建议取值 1 ~ 10
created_at
updated_at
```

## 注意

**Track 不直接属于 Album。**

正确的实体链路是：

```text
Album
  |
Release
  |
ReleaseTrack
  |
Track
```

---

# 十一、TrackArtist

歌曲和艺术家的多对多关系。

例如：

```text
周杰伦 feat. 蔡依林
```

## 已实现字段

```text
track_artist
--------------------------------
id                  bigint unsigned PK
track_id            bigint unsigned FK → track.id
artist_id           bigint unsigned FK → artist.id
credited_name       varchar(255)      该歌曲中的署名
join_phrase         varchar(255)      艺术家之间的连接词
```

索引：

```text
UNIQUE uk_track_artist (track_id, artist_id)
INDEX  idx_track_artist_track_id (track_id)
INDEX  idx_track_artist_artist_id (artist_id)
FOREIGN KEY fk_track_artist_track  → track(id)  ON DELETE CASCADE
FOREIGN KEY fk_track_artist_artist → artist(id) ON DELETE CASCADE
```

## 待补字段：role

```text
role    艺术家在该歌曲中的角色
```

取值：

```text
演唱
作词
作曲
制作
编曲
```

> **注意**：MusicBrainz 的 `artist-credit` 只提供署名与连接词，**不包含角色**。role 需要通过 recording 的 `relations` 接口额外获取（相当于额外的 API 调用）。因此第一阶段先不实现。
>
> 一旦加入 role，唯一键 `(track_id, artist_id)` 就会失效——同一人可能同时是「作词」和「作曲」，需要改成 `(track_id, artist_id, role)`。

---

# 十二、音乐标签体系

在第一阶段核心实体之上，MusicMind 扩展出 5 类标签维度：

```text
Genre
Mood
Scene
Language
Region
```

这 5 类标签**不来自 MusicBrainz**，属于 MusicMind 自有数据，需要独立的标注流程（后续可由 LLM + Embedding 辅助生成）。

---

# 十三、Genre

音乐类型。

例如：

```text
流行
摇滚
R&B
电子
```

表结构：

```text
Genre
--------------------------------
id
name
parent_id
description
created_at
updated_at
```

支持层级结构：

```text
流行
└── 华语流行
```

---

# 十四、TrackGenre

```text
Track N ─── M Genre
```

表结构：

```text
TrackGenre
--------------------------------
id
track_id
genre_id
created_at
```

---

# 十五、Mood

音乐情绪。

例如：

```text
治愈
忧郁
青春
怀旧
```

表结构：

```text
Mood
--------------------------------
id
name
description
created_at
updated_at
```

---

# 十六、TrackMood

```text
Track N ─── M Mood
```

---

# 十七、Scene

使用场景。

例如：

```text
学习
编程
通勤
夜晚
运动
```

---

# 十八、TrackScene

```text
Track N ─── M Scene
```

---

# 十九、Language

歌曲语言。

例如：

```text
中文
粤语
英语
日语
纯音乐
```

---

# 二十、TrackLanguage

```text
Track N ─── M Language
```

---

# 二十一、Region

音乐地区。

例如：

```text
中国
 ├── 中国大陆
 ├── 中国香港
 └── 中国台湾
```

表结构：

```text
Region
--------------------------------
id
name
parent_id
description
created_at
updated_at
```

---

# 二十二、TrackRegion

```text
Track N ─── M Region
```

---

# 二十三、用户系统（第二阶段）

第一阶段**暂不实现**：

```text
User
Favorite
Playlist
PlaylistTrack
PlayHistory
```

原因：

第一阶段目标是**完成音乐知识库**。用户体系依赖真实的交互行为，等音乐数据层稳定后再实现。

字段设计留待第二阶段确定，届时参考：

```text
User            id / username / nickname / avatar / email / status
Favorite        user_id + track_id
Playlist        user_id / name / description / cover_url / is_public
PlaylistTrack   playlist_id + track_id + sort_order
PlayHistory     user_id / track_id / played_at / play_duration / completed
```

---

# 二十四、Artist Relation（后续）

艺术家之间关系：

```text
合作
影响
成员
师承
```

表结构：

```text
ArtistRelation
--------------------------------
id
source_artist_id
target_artist_id
relation_type
description
created_at
```

---

# 二十五、Similar Artist

不存固定关系。

采用：

```text
Embedding
+
Vector Search
+
RAG
```

动态计算。

---

# 二十六、第一阶段 MySQL 表

## 已在 `musicmind` 库中创建

```text
artist
artist_alias

album
album_artist

music_release
release_track

track
track_artist
```

## 下一步补充

```text
genre
track_genre

mood
track_mood

scene
track_scene

language
track_language

region
track_region
```

---

# 二十七、当前项目架构

```text
data-pipeline
│
├── musicbrainz
│    ├── client.py                 MusicBrainz API 客户端
│    ├── adapter.py                MusicBrainz 数据 → MusicMind 数据
│    │
│    └── repository
│         ├── artist_repository.py
│         ├── album_repository.py
│         ├── release_repository.py      (待建)
│         └── track_repository.py        (待建)
│
├── config
│    └── settings.py               MYSQL_CONFIG / MUSICBRAINZ_CONFIG
│
├── database
│    └── connection.py             (待建)
│
├── test
│
└── main.py                        (待建)
```

## Adapter 已实现的方法

```text
artist_to_musicmind
artist_aliases_to_musicmind

album_to_musicmind
album_artists_to_musicmind

release_to_musicmind
release_tracks_to_musicmind

track_to_musicmind
track_artists_to_musicmind
```

## 字段映射对照

| MusicMind | MusicBrainz | 说明 |
|-----------|-------------|------|
| artist.name | artist.name | |
| artist.sort_name | artist.sort-name | |
| artist.disambiguation | artist.disambiguation | |
| album.name | release-group.title | 取 `title` 字段，映射为 `name` |
| album.release_date | release-group.first-release-date | |
| album.primary_type | release-group.primary-type | |
| album.secondary_types | release-group.secondary-types | 数组 → JSON |
| release.title | release.title | |
| release.release_date | release.date | |
| release.country | release.country | |
| release.status | release.status | |
| track.name | recording.title | |
| track.duration_ms | recording.length | 毫秒 |
| *.credited_name | artist-credit[].artist.name | |
| *.join_phrase | artist-credit[].joinphrase | |

---

# 二十八、下一阶段开发路线

已完成：

```text
MusicBrainz Client
+
MusicBrainz Adapter
+
MySQL Schema
+
ArtistRepository / AlbumRepository
```

## 1. 完成所有 Repository

```text
ArtistAliasRepository
AlbumArtistRepository
ReleaseRepository
ReleaseTrackRepository
TrackRepository
TrackArtistRepository
```

## 2. 编写 Import Pipeline

目标是一句代码完成整条链路导入：

```python
import_artist("周杰伦")
```

自动执行：

```text
Artist
  ↓
Album
  ↓
Release
  ↓
Track
  ↓
Relations
  ↓
MySQL
```

## 3. 添加 AI 数据层

```text
MySQL
  |
  |
Embedding
  |
  |
Qdrant
  |
  |
RAG
  |
  |
Agent
```

---

# 二十九、待处理问题

按优先级排列，均为当前代码或 Schema 中已确认存在的缺口。

## 1. 所有表都缺少 `created_at` / `updated_at`

当前 8 张表均无时间戳字段。

影响：无法判断数据的导入时间，无法做增量同步（「只重新抓取 30 天内更新过的艺人」这类需求无法实现），出问题也无法溯源。

建议：至少给每张表加 `created_at` 和 `updated_at`。

## 2. `artist_alias` 缺少唯一约束，重复导入会插入重复数据

`ArtistRepository.upsert` 是幂等的（靠 `musicbrainz_id` 唯一键 + `ON DUPLICATE KEY UPDATE`），但 alias 没有对应的幂等保证。

建议：加 `UNIQUE (artist_id, name, locale)`，alias 写入走 `ON DUPLICATE KEY UPDATE`。

## 3. `AlbumRepository` 未写入 `album_artist`

Album 表本身没有 `artist_id` 列，专辑与艺术家的关系全部存在 `album_artist` 表。但当前 `AlbumRepository.upsert` 只写 `album` 表，`album_artist` 的写入逻辑尚未实现——导入专辑后，查不到这张专辑是谁的。

## 4. `release_track` 唯一键不支持同一首歌重复出现

`UNIQUE (release_id, track_id)` 导致双 CD / Bonus Disc 中重复收录的歌曲无法表达。

建议：改成 `UNIQUE (release_id, disc_number, track_number)`。

## 5. `TrackArtist.role` 与 `ReleaseTrack.created_at` 尚未实现

见第十一节、第九节说明。

---

# 三十、设计原则

最终形成三层职责：

| 层 | 回答的问题 |
|----|-----------|
| MySQL | **是什么？** |
| Qdrant / RAG | **相关知识是什么？** |
| Agent | **应该怎么做？** |

第一阶段只做：

```text
MySQL + 基础音乐业务
```

暂不加入：

```text
Agent
RAG
MCP
Embedding
复杂推荐算法
```

等基础音乐数据稳定之后，再逐步接入 AI 能力。
