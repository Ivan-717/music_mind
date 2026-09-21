# MusicMind 音乐数据模型 v2.1

> 本文档记录 MusicMind 的核心音乐领域模型与实际 MySQL Schema。
>
> 该模型将作为后续 MySQL 数据库设计、音乐数据导入、RAG 知识库、Agent Tool 设计的基础。

**版本：v2.1**

**相对 v2.0 的变化：**

1. 全部 8 张表补齐 `created_at` / `updated_at`
2. `artist_alias` 补 `UNIQUE (artist_id, name, locale)`，重复导入不再产生重复别名
3. `release_track` 唯一键由 `(release_id, track_id)` 改为 `(release_id, disc_number, track_number)`，支持双 CD 场景
4. 数据管道（`import_artist`）完成，新增第二十七节记录其架构与流程
5. 新增「中文数据与繁简政策」决策记录（第二十九节）

**v2.0 的核心设计（未变）：**

1. Album = MusicBrainz **Release Group**，Release 是具体发行版本
2. Track **不直接属于 Album**，链路为 `Album → Release → ReleaseTrack → Track`
3. Album / Track 与 Artist 均为 **N:M**，通过 `album_artist` / `track_artist` 中间表
4. MusicBrainz 通过 Data Adapter → Repository 写入 MySQL
5. 用户系统推迟到第二阶段

> **文档约定**
>
> 每张表分两部分：
> - **已实现字段** —— 当前 `musicmind` 库中真实存在的列
> - **待补字段** —— v2.1 设计中有、但尚未加入数据库的列（多为 MusicMind 自有的标注数据，不来自 MusicBrainz）

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
周杰倫
林俊傑
陳奕迅
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
created_at          timestamp         创建时间
updated_at          timestamp         更新时间
```

索引：

```text
UNIQUE uk_artist_musicbrainz_id (musicbrainz_id)
INDEX  idx_artist_name (name)
```

`musicbrainz_id` 用于关联外部音乐知识，例如：

```text
a223958d-5c56-4b2c-a30a-87e357bc121b
```

## 待补字段

```text
description     艺术家介绍
avatar          头像
country         国家
region_id       关联 region 表
debut_date      出道日期
```

## stub 机制

管道遇到「合作艺人」时，不会为了一个署名去递归抓取整个艺人。此时写入 **stub**（占位记录）：

```text
stub = 只填 musicbrainz_id + name 的 artist 行
```

`ArtistRepository.ensure_stub()` 的语义：

- 不存在 → 插入最小数据
- 已存在 → **不更新任何业务字段**（防止 stub 覆盖完整数据）

实现靠 `ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)`——把主键"更新"成它自己，唯一的副作用是让 `cursor.lastrowid` 带回已有行的 id。

后续对同一艺人执行 `import_artist(mbid)` 时，`upsert` 会原地把这一行升级成完整数据，**id 不变**。

> 实测：梁心頤最初作为周杰倫《珊瑚海》的 feat 艺人以 stub 形式入库（id=17，sort_name 为空），之后全量导入时同一行被升级（sort_name 填入 `Veronin, Lara`），id 仍是 17。

---

# 五、ArtistAlias

艺术家别名 / 译名。

例如：

```text
周杰倫 → Jay Chou / ジェイ・チョウ / 周杰伦
```

单独成表（而非 Artist 上的一个字段），因为一个艺术家有多个别名。

## 已实现字段

```text
artist_alias
--------------------------------
id                  bigint unsigned PK
artist_id           bigint unsigned FK → artist.id
name                varchar(255)      别名
locale              varchar(32)       语言/地区，如 zh_CN、en，NOT NULL DEFAULT ''
is_primary          tinyint(1)        是否为主要别名
created_at          timestamp         创建时间
updated_at          timestamp         更新时间
```

索引：

```text
UNIQUE uk_artist_alias (artist_id, name, locale)
INDEX  idx_artist_alias_artist_id (artist_id)
INDEX  idx_artist_alias_name (name)
FOREIGN KEY fk_artist_alias_artist → artist(id) ON DELETE CASCADE
```

> **`locale` 为什么 NOT NULL DEFAULT ''**：实测约 43% 的 MusicBrainz 别名没有 locale。若允许 NULL，唯一键会因为「NULL 不等于 NULL」而失效，重复导入会插入重复行。adapter 里用 `alias.get("locale") or ""` 兜底。

> **繁简政策**：MusicBrainz 的别名里天然包含简体版本（如周杰倫的 aliases 含「周杰伦」）。这是本地等值查询简体名称的主要兜底手段，详见第二十九节。

---

# 六、Album

Album 对应 MusicBrainz **Release Group**，表示一张音乐作品集合。

例如：

```text
《范特西》
《七里香》
《她說》
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
created_at          timestamp         创建时间
updated_at          timestamp         更新时间
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
```

## 关系

**Album 与 Artist 是 N:M**，通过 `album_artist` 关联（合辑、合作专辑、`周杰倫 & 方文山` 这类场景）。

```text
Album N ─── M Artist
          ↓
      AlbumArtist
```

> **注意**：Album 表本身没有 `artist_id` 列。专辑归属完全靠 `album_artist` 表表达，由管道写入——见第二十七节。

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
created_at          timestamp         创建时间
updated_at          timestamp         更新时间
```

索引：

```text
UNIQUE uk_album_artist (album_id, artist_id)
INDEX  idx_album_artist_album_id (album_id)
INDEX  idx_album_artist_artist_id (artist_id)
FOREIGN KEY fk_album_artist_album  → album(id)  ON DELETE CASCADE
FOREIGN KEY fk_album_artist_artist → artist(id) ON DELETE CASCADE
```

## 可更新字段

唯一键是 `(album_id, artist_id)`，所以 `ON DUPLICATE KEY UPDATE` 只能更新：

```text
credited_name
join_phrase
```

---

# 八、Release

Release 表示具体发行版本。

同一个 Album 可以有多个 Release，例如《范特西》：

```text
Album:
    范特西

Release:
    台湾 CD 版      2001-09-20   TW   10 首
    日本版          2006-02-22   JP   23 首（含 bonus tracks）
    马来西亚版       2001-01-01   MY   16 首
```

> 实测：周杰倫的《范特西》在 MusicBrainz 里有 **10 个发行版本**。这正是 Album 与 Release 必须分两层的原因——只按专辑名聚合会把它们混成一个数字。

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
created_at          timestamp         创建时间
updated_at          timestamp         更新时间
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

## 可更新字段

唯一键是 `musicbrainz_id`，所以 `ON DUPLICATE KEY UPDATE` 可以更新：

```text
album_id      ← MusicBrainz 编辑者重新挂载 release group 时保持同步
title
release_date
country
status
```

## 关系

```text
Album 1 ─── N Release
```

---

# 九、ReleaseTrack

发行版本中的歌曲列表。

例如《范特西》（台湾版）：

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
created_at          timestamp         创建时间
updated_at          timestamp         更新时间
```

索引：

```text
UNIQUE uk_release_track (release_id, disc_number, track_number)
INDEX  idx_release_track_release_id (release_id)
INDEX  idx_release_track_track_id (track_id)
FOREIGN KEY fk_release_track_release → music_release(id) ON DELETE CASCADE
FOREIGN KEY fk_release_track_track   → track(id)         ON DELETE CASCADE
```

> **唯一键为什么是「位置」而不是「歌曲」**：早期设计用 `(release_id, track_id)`，导致双 CD / Bonus Disc 中重复收录的同一首歌无法表达。改成 `(release_id, disc_number, track_number)` 后，唯一性由「第几张碟的第几轨」保证，与实体唱片一致。

## 可更新字段

唯一键是 `(release_id, disc_number, track_number)`，三者都不在更新列表里。唯一可更新的是：

```text
track_id      ← 同一位置换了一首歌的情况
```

> 这条语义只有在唯一键改成位置之后才成立。若沿用旧键，`track_id` 就在唯一键里，更新它会变成 no-op（实测验证过）。

## 空值处理

`track_number` 为 NULL 时，`ReleaseTrackRepository.upsert()` 直接 skip 并打 warning——`track_number` 是 NOT NULL 且属于唯一键，插入会失败。

`disc_number` 为 NULL 时兜底为 `1`。

---

# 十、Track

音乐作品（对应 MusicBrainz Recording）。

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
created_at                  timestamp         创建时间
updated_at                  timestamp         更新时间
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

**同一个 Track 可以被多个 Release 引用**（同一首歌出现在录音室版、演唱会版、精选集里）。实测：周杰倫全量导入时，2488 次 track upsert 最终只落成 852 行。

---

# 十一、TrackArtist

歌曲和艺术家的多对多关系。

例如：

```text
周杰倫 feat. 梁心頤
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
created_at          timestamp         创建时间
updated_at          timestamp         更新时间
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

## 已在 `musicmind` 库中创建（8 张，全部完成）

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

8 张表均含 `created_at` / `updated_at`。

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
├── main.py                        import_artist 管道 + CLI
│
├── musicbrainz
│    ├── client.py                 MusicBrainz API 客户端
│    ├── adapter.py                MusicBrainz 数据 → MusicMind 数据
│    │
│    └── repository
│         ├── artist_repository.py          upsert / ensure_stub
│         ├── artist_alias_repository.py
│         ├── album_repository.py
│         ├── album_artist_repository.py
│         ├── release_repository.py
│         ├── release_track_repository.py
│         ├── track_repository.py
│         └── track_artist_repository.py
│
├── config
│    └── settings.py               MYSQL_CONFIG / MUSICBRAINZ_CONFIG
│
├── database
│    └── connection.py             连接工厂
│
├── test
│    ├── conftest.py               db fixture（rollback，不落盘）
│    ├── fixtures/                 实测 API 响应样本（JSON）
│    ├── test_adapter.py           adapter 单元测试
│    └── test_repositories.py      repository 集成测试
│
├── pytest.ini
└── requirements.txt
```

密钥（MySQL 密码、MusicBrainz User-Agent）走环境变量，见仓库根目录的 `.env`（**不入 git**）。

## Adapter 方法

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
| artist_alias.locale | alias.locale | 缺失时兜底 `""` |
| artist_alias.is_primary | alias.primary | |
| album.name | release-group.title | 取 `title` 字段，映射为 `name` |
| album.release_date | release-group.first-release-date | 经 `normalize_date()` |
| album.primary_type | release-group.primary-type | |
| album.secondary_types | release-group.secondary-types | 数组 → JSON |
| release.title | release.title | |
| release.release_date | release.date | 经 `normalize_date()` |
| release.country | release.country | |
| release.status | release.status | |
| track.name | recording.title | |
| track.duration_ms | recording.length | 毫秒 |
| *.credited_name | artist-credit[].artist.name | |
| *.join_phrase | artist-credit[].joinphrase | |

## `normalize_date()` —— 部分日期

MusicBrainz 允许部分日期（如 `"1988-11"`、`"1988"`），MySQL 的 DATE 列会拒绝。`normalize_date()` 做补全：

| 输入 | 输出 |
|------|------|
| `"1988-11-15"` | `"1988-11-15"` |
| `"1988-11"` | `"1988-11-01"` |
| `"1988"` | `"1988-01-01"` |
| 空 / 非法 | `None` |

## `import_artist()` —— 数据管道

一句话导入一个艺人的全部作品：

```python
import_artist("周杰倫")
```

流程：

```text
① 解析艺人
     UUID 格式  → get_artist(mbid, inc="aliases")
     否则       → search_artist(name) → 取第一条 → get_artist(mbid, inc="aliases")

② 写艺人 + 别名 → commit（艺人本体先落地，后面失败也不丢）

③ browse 分页发现 release
     get_artist_releases(mbid, limit, offset, inc="release-groups")
     终止条件：本页返回数 < page_size
     按 release id 去重（防分页漂移）

④ 内存过滤（零额外请求）
     status        默认 {"Official"}
     primary-type  默认 {"Album", "EP", "Single"}

⑤ 逐 release 处理（每个 1 个详情请求）
     get_release(mbid)  ← inc=recordings+release-groups+media+artist-credits
        ├─ release-group  → album          （走 album_ids 缓存）
        ├─ artist-credit  → album_artist   （合作艺人走 ensure_stub）
        ├─ release 本体    → music_release
        └─ media[].tracks[]
              ├─ recording → track
              ├─ artist-credit → track_artist
              └─ release_track（位置信息）
     每个 release 结束 commit 一次
```

### 关键设计决策

| 决策 | 原因 |
|------|------|
| browse 必须带 `inc=release-groups` | 否则响应里没有 `release-group` 字段，primary-type 过滤会全灭（实测踩过） |
| 分页用「本页返回数 < 页大小」终止，不用 `release-count` | 翻页期间 MusicBrainz 数据会变，`release-count` 会漂移；`release-count` 只用于打印进度 |
| Repository 不解析 MBID | parent 的 upsert 返回本地 id，管道持 `mbid→id` 缓存换给 child（FK 列入参是本地 id） |
| 每 release commit 一次 | 中断后直接重跑即断点续导，不需要断点状态文件 |
| 合作艺人用 stub，不递归抓取 | 避免为了一个署名抓一整个艺人 |
| 提交粒度 = 一个 release | 实测 288～339 秒导入 208 个 release，中断只损失最后一个 |

> **断点续导实测**：一次导入在第 198 个 release 处被中断，重跑后只补了 5 个新 release，203 个已存在的原样更新，无重复行。

## 幂等性

所有写入靠唯一键 + `ON DUPLICATE KEY UPDATE`，重复运行不增行。

MySQL 8 中 `VALUES()` 已弃用，统一使用行别名语法：

```sql
INSERT INTO album (musicbrainz_id, name, ...)
VALUES (%s, %s, ...) AS new
ON DUPLICATE KEY UPDATE
    name = new.name,
    ...
```

> **`ON DUPLICATE KEY UPDATE` 的填写规则**：只列「不在唯一键里、且会变化」的列。列在唯一键里的字段更新它等于 no-op。

---

# 二十八、下一阶段开发路线

已完成：

```text
MusicBrainz Client
+
MusicBrainz Adapter
+
MySQL Schema（8 张表 + 约束修复）
+
全部 8 个 Repository
+
import_artist 数据管道
+
测试（22 个用例，adapter 单测 + repository 集成测试）
```

## 1. 标签体系表

```text
genre / track_genre
mood / track_mood
scene / track_scene
language / track_language
region / track_region
```

加上这 10 张表后，MySQL 知识库的骨架才完整。

## 2. 批量导入

当前 `import_artist()` 一次一个艺人。下一步可以：

```text
批量艺人列表导入
+ 增量同步（只重抓 updated_at 超过 N 天的数据）
```

（`created_at` / `updated_at` 已在 8 张表落地，增量同步的前置条件已具备）

## 3. AI 数据层

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

# 二十九、决策记录与待处理问题

## 决策记录

### 1. 中文数据与繁简政策

**决策**：数据管道**忠实保存 MusicBrainz 原样数据**（繁体），繁简转换放在展示层 / Agent 层。

原因：

- 繁简转换不可逆（異体字、港台专名、日文汉字转错无法溯源）
- 项目定位是「事实库」，应忠实于上游数据源
- 增量同步、数据对账时，转换过的数据会对不上

代价：MySQL 直接等值查询简体名称搜不到繁体行。artist 层靠 `artist_alias` 兜底（周杰倫的 aliases 含简体「周杰伦」），album / track 层较弱，需要展示层或 Agent 处理。

### 2. 数据源语言的现实

MusicBrainz 的华语数据以**繁体**为主：

```text
周杰倫 / 范特西 / 愛在西元前 / 葉惠美
```

这是上游数据的真实形态，不是导入过程产生的。

## 待处理问题

### 1. `TrackArtist.role` 未实现

见第十一节。需要 recording 的 `relations` 接口，属于额外 API 调用，第一阶段跳过。

一旦加入，唯一键需改为 `(track_id, artist_id, role)`。

### 2. `import_artist()` 的统计口径

`ImportStats` 统计的是 **upsert 调用次数**，不是实际新增行数。

实测：周杰倫全量导入报告 `Track: 2488`，但库中只有 852 行 track——因为同一首歌被多个 release 引用。

不影响正确性（幂等本身没问题），但输出有误导性。修法：在管道里加 `track_ids` / `release_ids` 缓存。

### 3. `release_track` 的「同位置换歌」语义尚未被数据触发

唯一键改为 `(release_id, disc_number, track_number)` 后，`track_id` 成为可更新字段。这个分支在真实数据里很少触发，目前只有集成测试覆盖。

### 4. 5 张标签表的表结构尚未落地

见第二十八节第 1 项。

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
