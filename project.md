# MusicMind —— AI 音乐探索与个性化 Agent 平台

> 项目定位：基于 AI Agent 的个性化音乐探索平台
> 项目目标：通过自然语言理解、RAG、Tool Calling、Memory、LangGraph、MCP 等技术，让 AI Agent 帮助用户完成音乐搜索、推荐、分析、探索和歌单生成。

---

## 一、项目概述

### 1.1 项目名称

**MusicMind**

### 1.2 项目类型

AI Agent + 音乐探索 + 个性化推荐平台

### 1.3 一句话定义

> MusicMind 是一个基于 AI Agent 的个性化音乐探索平台，用户可以通过自然语言表达自己的音乐需求，Agent 综合音乐知识、音乐数据和用户个人偏好，完成音乐搜索、推荐、分析、歌单生成以及音乐探索路径规划。

### 1.4 核心定位

MusicMind 不是一个简单的：

> “AI 聊天机器人 + 音乐推荐”

而是一个真正具有 **Agent Workflow** 的 AI 应用。

用户提出一个音乐需求后，Agent 能够：

```text
理解用户意图
    ↓
分析任务
    ↓
选择合适的工具
    ↓
搜索音乐数据
    ↓
检索音乐知识
    ↓
分析用户偏好
    ↓
生成候选结果
    ↓
评估结果是否满足要求
    ↓
必要时重新执行
    ↓
返回最终结果
```

---

# 二、项目背景

传统音乐应用通常依赖：

* 关键词搜索
* 标签筛选
* 固定推荐算法
* 播放历史
* 相似歌曲推荐

这种方式适合结构化需求，但用户很多时候并不能准确描述自己想找什么。

例如：

> “我最近很喜欢 Radiohead，但是最近不太想听那么压抑的音乐，给我推荐一些类似的 Alternative Rock，最好是 1995～2010 年之间的。”

这个需求同时包含：

```text
艺术家偏好：Radiohead
音乐类型：Alternative Rock
时间范围：1995～2010
相似性：与 Radiohead 类似
情绪：不要过于压抑
隐含需求：探索新的音乐
```

这类需求已经不是简单的数据库查询。

因此，本项目希望通过 AI Agent 将：

```text
自然语言
    ↓
意图理解
    ↓
任务规划
    ↓
工具调用
    ↓
知识检索
    ↓
个性化分析
    ↓
结果评估
    ↓
最终回答
```

形成完整的音乐探索流程。

---

# 三、项目目标

## 3.1 用户目标

让用户能够使用自然语言完成音乐探索。

例如：

```text
“推荐一些适合晚上开车听的日系摇滚。”

“我喜欢 Radiohead，还可以听什么？”

“我想从 Oasis 开始了解 Britpop。”

“根据我最近听的歌分析一下我的音乐口味。”

“帮我生成一个适合深夜写代码的 20 首歌单。”
```

---

## 3.2 技术目标

通过项目实践掌握并真正理解：

* LangChain
* LangGraph
* Tool Calling
* Structured Output
* RAG
* Embedding
* Vector Database
* Agent Memory
* Checkpoint
* Retry / Fallback
* MCP
* Agent Evaluation
* Observability
* Docker
* Docker Compose
* Linux 部署

---

## 3.3 工程目标

项目最终不仅要能够运行，还需要具备完整的软件工程能力：

* 前后端分离
* AI Agent 独立服务
* 数据持久化
* 缓存
* 向量数据库
* 日志
* 错误处理
* Agent Trace
* Evaluation
* Docker 部署
* 项目文档
* 架构设计
* 可维护代码结构

---

# 四、核心功能

## 4.1 自然语言音乐搜索

用户通过自然语言描述自己的音乐需求。

例如：

> “找一些 2000 年代的英伦摇滚，适合晚上听，不要太吵。”

Agent 自动解析：

```text
时间：2000～2009
地区：英国
类型：Rock
场景：夜晚
能量：中低
```

然后调用音乐搜索工具完成搜索。

---

## 4.2 个性化音乐推荐

根据用户历史行为建立音乐偏好。

数据来源包括：

* 收藏
* 评分
* 播放记录
* 搜索记录
* 创建的歌单
* 推荐反馈
* 对话记录

最终形成：

```text
User Music Profile
```

Agent 根据用户画像进行个性化推荐。

---

## 4.3 音乐知识 RAG

建立音乐知识库。

知识内容包括：

* Artist
* Album
* Track
* Genre
* Subgenre
* Era
* Music History
* Artist Influence
* Similar Artist
* Music Scene

典型问题：

> “Oasis 和 Blur 为什么经常被放在一起讨论？”

Agent 通过 RAG 检索相关知识后回答。

---

## 4.4 音乐探索路径

帮助用户系统性了解一个音乐领域。

例如：

```text
Oasis
  ↓
Blur
  ↓
Pulp
  ↓
Suede
  ↓
Britpop
  ↓
90s British Indie
```

每个探索节点包含：

* 艺术家 / 专辑 / 歌曲
* 代表作品
* 音乐背景
* 与上一节点的关系
* 推荐原因
* 下一步探索方向

---

## 4.5 音乐品味分析

分析用户长期音乐行为。

例如：

```text
常听音乐类型
喜欢的年代
喜欢的地区
常听艺术家
情绪偏好
音乐能量
音乐探索程度
```

系统最终生成用户音乐画像。

---

## 4.6 智能歌单生成

用户可以提出：

> “生成一个 20 首适合深夜写代码的歌单。”

Agent 综合：

```text
用户偏好
+
场景
+
音乐类型
+
情绪
+
音乐数据
```

生成符合要求的歌单。

---

# 五、Agent 的职责

Agent 负责非确定性的智能任务。

包括：

```text
自然语言理解
意图分析
任务规划
工具选择
音乐搜索
知识检索
用户偏好分析
推荐生成
结果评估
任务重试
自然语言解释
```

---

# 六、普通后端的职责

Spring Boot 后端负责确定性的业务逻辑。

包括：

```text
用户
登录
注册
权限
歌曲
歌手
专辑
歌单
收藏
评分
播放记录
搜索记录
用户反馈
数据库
缓存
API
```

---

# 七、Agent 与后端的边界

核心原则：

> **Spring Boot 负责确定性的业务逻辑，Agent 负责非确定性的智能决策。**

整体关系：

```text
Spring Boot
    ↓
“系统应该怎么运行”

Agent
    ↓
“面对用户当前需求，我下一步应该做什么”
```

---

# 八、技术架构

整体架构：

```text
                         ┌──────────────┐
                         │   Vue 3      │
                         │ TypeScript   │
                         └──────┬───────┘
                                │
                                ▼
                         ┌──────────────┐
                         │ Spring Boot  │
                         │    API       │
                         └──────┬───────┘
                                │
                                ▼
                    ┌──────────────────────┐
                    │ Python Agent Service │
                    │                      │
                    │ LangChain            │
                    │ LangGraph             │
                    └──────────┬───────────┘
                               │
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
          Tools              RAG              Memory
             │                 │                 │
             └─────────────────┼─────────────────┘
                               │
                               ▼
                        Music MCP Server
                               │
                 ┌─────────────┼─────────────┐
                 ▼             ▼             ▼
              MySQL         Qdrant       外部数据源
                 │
                 ▼
               Redis
```

---

# 九、技术栈

## 9.1 前端

```text
Vue 3
JavaScript
Vite
ECharts
```

> **偏离说明（2026-09-29）**：原计划 TypeScript，实际采用 JavaScript。
> 理由：项目重心在 Python Agent 层，TS 是纯增量成本；前端已完成 10 个文件，
> 迁移收益低于成本。若后期要补，Vue SFC 支持逐文件混用 `lang="ts"`。

---

## 9.2 后端

```text
Java
Spring Boot
MyBatis / MyBatis-Plus
MySQL
Redis
```

---

## 9.3 AI Agent

```text
Python
LangChain
LangGraph
LLM API
Tool Calling
Structured Output
```

---

## 9.4 RAG

```text
Embedding
Vector Database
Qdrant
Retriever
Metadata Filtering
```

---

## 9.5 MCP

建立独立的：

```text
Music MCP Server
```

提供音乐相关工具，例如：

```text
search_tracks
search_artists
search_albums
get_artist
get_album
get_similar_tracks
search_music_knowledge
create_playlist
```

MCP 的目的不是为了增加一个技术名词，而是将：

```text
Agent
    ↓
音乐能力
```

进行解耦。

---

## 9.6 工程与部署

```text
Docker
Docker Compose
Nginx
Linux
Git
```

---

# 十、项目开发原则

## 原则 1：先完成业务，再增加 AI

不要一开始就堆 Agent。

先保证基础音乐业务系统能够运行，再逐步增加：

```text
RAG
 ↓
Agent
 ↓
Memory
 ↓
MCP
 ↓
Evaluation
 ↓
Observability
```

---

## 原则 2：技术必须有实际用途

不为了简历关键词强行加入：

```text
Multi-Agent
Kafka
分布式锁
微服务集群
复杂消息队列
```

如果没有实际需求，就不加入。

---

## 原则 3：优先单 Agent + Workflow

第一阶段采用：

```text
Single Agent
+
LangGraph Workflow
+
Multiple Tools
```

只有当系统真正出现明确的职责拆分需求时，才考虑 Multi-Agent。

---

## 原则 4：Agent 必须能够解释自己的结果

推荐结果不能只是：

```text
歌曲 A
歌曲 B
歌曲 C
```

而应该能够说明：

```text
为什么推荐？
满足了哪些条件？
和用户过去喜欢的音乐有什么关系？
```

---

## 原则 5：结果质量必须能够被评估

LLM 输出具有随机性。

因此后期需要建立 Evaluation：

```text
Tool Accuracy
Constraint Satisfaction
RAG Accuracy
Recommendation Quality
Task Success
Latency
Token Usage
```

---

# 十一、项目最终版本

最终目标不是：

> “做一个使用 LangGraph 的音乐网站。”

而是：

> **独立设计并实现一个完整的 AI Agent 音乐探索系统。**

系统具备：

```text
Java Backend
      +
Python Agent Service
      +
LangGraph Workflow
      +
RAG
      +
Tool Calling
      +
Memory
      +
MCP
      +
Checkpoint
      +
Retry / Fallback
      +
Evaluation
      +
Observability
      +
Docker Deployment
```

---

# 十二、项目最终能力结构

```text
                    MusicMind
                       │
        ┌──────────────┼──────────────┐
        │              │              │
      音乐数据        音乐知识        用户数据
        │              │              │
        ▼              ▼              ▼
      Tools           RAG          User Profile
        │              │              │
        └──────────────┼──────────────┘
                       │
                       ▼
                  AI Agent
                       │
                ┌──────┴──────┐
                │             │
             Workflow       Memory
                │             │
                └──────┬──────┘
                       ▼
                  Evaluation
                       │
                       ▼
                 Final Result
```

---

# 十三、项目完成后的简历描述方向

项目名称：

**MusicMind —— AI 音乐探索与个性化 Agent 平台**

项目描述：

> 基于 Java + Spring Boot + Python + LangGraph 构建 AI 音乐探索平台，通过 RAG、Tool Calling、Memory、MCP 等技术实现自然语言音乐搜索、个性化推荐、音乐知识问答、音乐探索路径及智能歌单生成，并构建 Agent Evaluation 与 Observability 体系，对 Agent 的任务成功率、工具调用准确性、约束满足度、延迟及 Token 消耗进行评估与监控。

---

# 十四、项目开发阶段

### Phase 0：项目定义

当前阶段。

```text
项目定位
核心功能
技术栈
系统边界
开发原则
```

---

### Phase 1：基础音乐业务系统

功能：

```text
用户
音乐
歌手
专辑
歌单
收藏
评分
搜索
播放记录
首页策展
```

技术：

```text
Vue 3 (JavaScript)
Spring Boot
MySQL
Redis
```

**进度（2026-09-30）**

```text
✅ 认证           注册 / 登录 / JWT / 权限锁定
✅ 收藏           增删查 + 分页 + 用户隔离
✅ Vue 3 前端     登录闭环 / 专辑列表 / 专辑详情 / 收藏页
✅ 歌单后端       CRUD + 曲目管理 + 归属校验
✅ 繁简转换       展示层转换，数据层存繁体原样
✅ 封面抓取管道   Cover Art Archive，250 张专辑
✅ 搜索           曲目 / 专辑 / 歌手，含繁简变体扩展与歌手名匹配
✅ 歌手页         专辑按发行日期排，复用专辑详情页
✅ MusicBrainz 查询  本地搜不到时看上游有什么
✅ 歌单前端       「我的歌单」页（导入歌单管理，见 Phase 1.5）

⬜ 封面按需代理   含可淘汰缓存 + 种子
⬜ 播放记录
⬜ 评分           需先建表
⬜ Redis
⬜ 首页策展       需先建策展表
```

**这些剩下的项已【降级】**——2026-09-30 重新审视产品用法后认定它们不是入口，
详见下一节 Phase 1.5。做完导入之后再回头看哪些仍然需要。

---

### Phase 1.5：用户歌单导入 ← **当前重点**

> 2026-09-30 重新审视产品用法后**提前到最前**。
>
> 用户实际是这样用的：
>
> ```text
> 注册 → 导入自己的歌单 → 系统对齐入库 → 收藏
>                                     ↓
>                           分析音乐人格 → 推荐 → 试听
> ```
>
> **这条链的第一环是「导入」。** 没有它，后面的「人格分析」「推荐」都没有数据。
> Phase 1 剩下的项（歌单前端 / 评分 / Redis / 首页策展）都不是入口，全部降级。

```text
① 导入歌单      用户带着自己的歌单来
      ↓
② 实体对齐      外部文本 → MusicBrainz MBID      ← 真正的难点
      ↓
③ 按需入库      本地没有的抓进来                  ← 顺带解决「搜某歌手搜不到」
      ↓
④ 音频试听      iTunes preview，30 秒，流式
      ↓
⑤ 音乐人格分析  Agent 的起点
      ↓
⑥ 推荐
```

---

**① 导入入口：直接做链接导入**

> 2026-09-30 实测后定。原本打算「先粘贴文本、后换链接」，被实测推翻。

```text
网易云   GET music.163.com/api/playlist/detail?id=<歌单ID>
         → 一次请求，200 首，每条带 歌名 / 歌手 / 专辑 / 时长

QQ音乐   GET c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg?disstid=<歌单ID>&...
         → 一次请求，76 首，同样带全

两者都不需要加密、不需要登录、不需要额外服务。
```

**链接导入不只是「更符合需求」，技术上更好**：

```text
            文本粘贴        链接导入
时长        没有            有 ← 实体对齐最有效的校验信号
专辑名      没有            有 ← 又一路校验
格式歧义    要猜哪边是歌手   结构化字段，零歧义
额外代码   一个宽容解析器    一个抓取方法（~50 行）
```

**代价（必须写清）**

```text
1. 非官方接口 —— 没有文档保证，随时可能变
2. 碰 ToS —— 个人学习研究可以；做成公开服务是另一回事
3. 所以：做成可替换的 Provider 接口（网易云 / QQ 各一个实现），
   抓取失败要明确报错，不能静默
```

**不做文本粘贴兜底**——那是「为可能发生的变化先写一套代码」，
违背「原则 2：技术必须有实际用途」。真变了再说。

**② 实体对齐（Entity Resolution）**

```text
外部文本（"周杰伦 - 晴天"） → MusicBrainz MBID

分层匹配，宁可少匹配，不可错匹配：
  1. 艺人名 + 曲名 精确匹配
  2. 规范化后匹配（繁简归一 / 去 feat. 括号 / 大小写）
  3. 时长校验（差 < 3 秒才算命中）—— 筛掉同名不同版本
  4. 匹配不上的标记 unresolved，不硬凑

【不在本阶段做】LLM 兜底 —— 留给 Agent 阶段。
先证明确定性规则不够用，再上 LLM（符合「原则 2：技术必须有实际用途」）。
```

**③ 按需入库（On-demand Ingestion）**

```text
【粒度问题待定】用户歌单里一首《晴天》被导入时，抓多少？
   a. 只抓这一首        → 造出「孤儿曲目」，专辑详情页是空的
   b. 抓它所属的整张专辑 → 用户点进专辑能看到上下文   ← 倾向这个
   c. 抓艺人全部作品     → 太大（薛之谦在 MusicBrainz 有 1261 个结果）

【为什么必须有这一步】
  现有库只有 250 张专辑 / 1898 首曲目，覆盖少数几个艺人。
  导入一个 50 首的歌单，本地能匹配上的可能只有个位数。
  不做按需入库，导入功能就是摆设。
```

**④ 音频试听**

```text
iTunes Search API 的 previewUrl —— 30 秒片段，官方、合法。
实测：itunes.apple.com 可达（0.7s），能下到 audio/x-m4p。

前端只放个 <audio>，**流式播放，不落地**（音频一个字都不存）。

【诚实设计】匹配不上就不给播放按钮，而不是给一个播不了的。
```

**架构上的意义**

```text
从「离线全量管道」升级为「离线种子 + 在线按需入库」
→ 库随用户使用而增长，而不是靠一次性全量导入
```

**实现进度（2026-09-30）**

```text
✅ ① 导入入口    网易云 / QQ 音乐 Provider，链接导入，整单落库（标题/歌手/专辑/时长/封面/外部 id）
✅ ② 实体对齐    繁简变体 + 艺人名 + 曲名的确定性匹配，结果写回 user_playlist_track
✅ 歌单管理      「我的歌单」页：分页 / 封面 / 逐首剔除 / 删除整单 / 归属校验
✅ 状态筛选      全部 / 已收录 / 未收录（筛在【服务端】，否则分页和总数会对不上）
✅ 收藏解耦      导入默认不动收藏；导入时可选，事后可单首 / 勾选批量 / 整单收藏

✅ ③ 按需入库    点「入库」→ 后台按专辑抓 MusicBrainz → 自动重新对齐（见下）
⬜ ④ 音频试听
⬜ ⑤ 音乐人格分析
```

**①② 的验收实测（2026-09-30，③ 之前）**

```text
后端 64/64、前端 26/26 通过。
导入 200 首耗时 3.1s（约 15ms/首，含逐首对齐 + 写回）——
按此推算 814 首约 12s，同步导入可以接受，异步 + 进度条不是现在的瓶颈。

真实匹配率：网易云热歌榜 200 首里本地库只能对上 2 首。
本地库是 MusicBrainz 的西方音乐为主，中文流行歌几乎没有。
→ 这印证了 ③ 按需入库是导入功能能不能用的前提，不是锦上添花。
```

**①② 踩到的两个坑**

```text
1. 对齐结果必须【写回库】。
   只放进接口返回的摘要里，前端读 user_playlist_track 就永远是 PENDING，
   所有 ♡ 都被禁用、整单收藏收藏 0 首 —— 整个收藏功能是死的。

2. MySQL JDBC 默认 useAffectedRows=false：
   UPDATE 返回「匹配行数」而不是「改变行数」。
   重复剔除同一首照样返回 1，调用方就没法用返回值判断 404。
   凡是靠返回值判断「有没有改动」的地方，WHERE 里都要带上状态条件。
```

**③ 按需入库的设计（2026-09-30）**

粒度是**整张专辑（release）**，不是整位歌手。用户否掉了整位歌手：
「一首歌就把一个歌手所有抓取 是否太不划算」。实测成本印证了这个判断——
专辑粒度实测约 4 秒/首（整位歌手要 20~90 秒/位，200 首要两小时）。

```text
用户在歌单页点「入库」
      ↓
Java：搜 MusicBrainz 录音 → 挑一张 release → 落一行 ingestion_job
      ↓
Java：子进程 python ingest_release.py <release-mbid>   ← 写库是 Python 的活
      ↓
Java：回头把全库「还没对齐 + 艺人像这个人」的行重跑一遍对齐
      ↓
那些行翻成 MATCHED → ♡ 和勾选框解禁
```

**三条不能动的边界**

```text
1. 写库的只有 Python。
   音乐侧的表归 data-pipeline 写（见 schema-user.sql 头注释）。
   在 Java 里重写一遍入库逻辑，两边迟早漂移，而漂移出来的 bug
   表现为「某些歌莫名其妙查不到」，极难定位。
   Java 负责的只有：解析（选哪张 release）、排队、以及入库后的重新对齐。

2. 队列全局共享，不按用户隔离。
   入库产物是所有人共用的音乐侧表。甲歌单里的歌不会因为乙点了「入库」
   而变得不能被甲收藏 —— 谁先点谁出力，成果大家用。user_id 只用于审计。

3. 不做「同一张 release 的活跃任务合并」。
   合辑里不同歌手的歌属于同一张 release，合并后按 A 的艺人范围
   重匹配不到 B 的行，B 会永久卡在 UNRESOLVED（正确性 bug）。
   同专辑重复入库改用「这张 release 有 DONE 过的任务就跳过子进程」兜底：
   幂等 + 省一次抓取，且不影响各自的重匹配范围。
```

**验收实测（2026-09-30）**

```text
接口 25/25、界面 14/14、pytest 27 passed。

单首入库：约 4 秒（搜录音 1~2s + 子进程 ~1.4s；早期版本还有一次多余的
「查 release」请求，后来发现搜索结果里本来就带 releases，已删掉）
一张专辑往往能救回不止一首 —— 抓《未完成》重对齐了 6 行，
抓《逆光》重对齐了 11 行。这是按专辑而不是按单曲抓的收益。

整个热歌榜 200 首可以一次排进队列（195 首）。
崩溃恢复：进程被杀后重启，RUNNING 自动打回 QUEUED。

**速度是被 MusicBrainz 限速卡死的，不是实现问题。**
它要求 1 请求/秒，每首歌至少要 1~2 次请求（严格搜不到就再宽松搜一次），
即每首 2~4 秒。814 首的歌单冷启动约 30~40 分钟——这是硬底。
能省的三处都省了（见下），再快就要违反它的限速了。

**真实命中率约 50%，但分布极不均匀。**
网易云热歌榜 200 首：中文说唱（艾志恒Asen / THOME / TizzyT / PSY.P…）
几乎全军覆没，主流流行（薛之谦 / 王力宏 / 周兴哲 / 孙燕姿）基本都能找到。
队列按加入顺序跑，早期正好排到说唱那批，一度看起来像「71% 找不到」——
那不是总体命中率，是采样偏差。
```

**踩到的三个坑（都是实测才暴露的）**

```text
1. 【时长不能用来硬过滤，只能用来排序】
   track.duration_ms 是 BIGINT UNSIGNED，直接相减出负数时 MySQL 不是返回
   负数，而是报 "BIGINT UNSIGNED value is out of range" —— 整条 SQL 失败、
   整个导入 500。必须 CAST AS SIGNED。

   更麻烦的是语义：一开始写成 ABS(差) < 3000 的硬过滤，结果歌单里
   《出现又离开 (Live)》404 秒、MusicBrainz 同一首现场版 416 秒，
   差 12.6 秒被判成「不同版本」，那行永远对不上、永远收藏不了。
   改成 ORDER BY 时长距离最近优先：同名多版本时挑对的那一个，
   只有一个候选时照样匹配。宁可匹配一个略长的版本，
   也不要让用户看着一首明明在库里的歌点不动收藏。

2. 【Windows 下 Python 输出重定向会用 GBK】
   子进程打印 ✓ 和中文错误信息时直接抛异常，退出码和日志全都不可信。
   ingest_release.py 里自己 reconfigure 成 UTF-8，不指望调用方设环境变量。
   另外 ProcessBuilder 必须 redirectErrorStream(true)：
   分两个流而只读一个，另一个写满缓冲区时子进程会阻塞在 write 上，
   Java 这边 waitFor 到超时 —— 一个假死。

3. 【排队那一刻就可能已经对上了】
   专辑已经被别人抓过时，后端在排队时就顺手写回了对齐结果，不会产生任务。
   前端如果只靠轮询刷新，那一行会一直显示「未收录」，用户以为点了没反应。
   必须拿响应里的 skippedAlreadyMatched 主动重取一次当前页。
```

---

### Phase 2：音乐知识库 + RAG

```text
数据整理
 ↓
文档处理
 ↓
Chunk
 ↓
Embedding
 ↓
Qdrant
 ↓
Retriever
 ↓
LLM
```

---

### Phase 3：第一个 Music Agent

```text
用户
 ↓
Intent
 ↓
Task
 ↓
Music Search
 ↓
RAG
 ↓
Answer
```

技术：

```text
Python
LangChain
LangGraph
Tool Calling
Structured Output
```

---

### Phase 4：个性化 Agent

加入：

```text
User Profile
User Behavior
Memory
```

实现真正的个性化推荐。

---

### Phase 5：复杂任务 Workflow

形成：

```text
Planner
 ↓
Search
 ↓
RAG
 ↓
Recommendation
 ↓
Evaluator
 ↓
Retry
 ↓
Final Answer
```

---

### Phase 6：Music MCP

建立：

```text
Music MCP Server
```

统一音乐相关工具。

---

### Phase 7：音乐探索系统

实现：

```text
Artist
 ↓
Genre
 ↓
Scene
 ↓
Album
 ↓
Related Artist
```

形成音乐探索路径。

---

### Phase 8：Agent Engineering

加入：

```text
Agent Trace
Logging
Retry
Fallback
Checkpoint
Token Tracking
Latency Tracking
Cost Tracking
```

---

### Phase 9：Agent Evaluation

建立测试集：

```text
100+ Agent Tasks
```

评估：

```text
Tool Accuracy
Constraint Satisfaction
RAG Accuracy
Recommendation Quality
Task Success
Latency
Token Usage
```

---

### Phase 10：完整部署

最终：

```text
Vue
 ↓
Nginx
 ↓
Spring Boot
 ↓
Python Agent
 ↓
MySQL
Redis
Qdrant
MCP
```

使用：

```text
Docker
Docker Compose
Linux
```

完成完整部署。

---

# 十五、数据与存储原则

> 2026-09-29 确定。核心判断：**该担心的不是「存不下」，是「等太久」。**

## 15.1 数据分三层

```text
【本地存】
  音乐元数据（曲目 / 专辑 / 艺人）
      958 字节/首（含 track + track_artist + release_track 三表）
      100 万首   ≈ 914 MB
      100 万专辑 ≈ 11 GB

  用户数据（收藏 / 歌单 / 播放记录）
      核心资产，Phase 4 的用户画像靠它

  首页策展
      冷启动保底 + 隔离外部依赖

【本地不存】
  音频      只在播放时流式拉取，只存 URL
  全部封面  按需抓 + 可淘汰缓存，不进 git
```

**为什么元数据必须存本地**

```text
不存本地 → 搜索要实时打 MusicBrainz（1 req/s，搜一次等 5 秒）
         → MusicBrainz 挂了，系统就挂了
         → Phase 2 的 RAG 做不了（向量检索必须有本地数据做 embedding）
```

**真正的约束是时间，不是磁盘**

```text
抓一个艺人的作品要走 MusicBrainz，限速 1 请求/秒。
Radiohead 有 20 张专辑 ≈ 20+ 次请求 ≈ 20 秒。
用户能感知的是「等 20 秒」，不是「占 20 KB 磁盘」。
```

---

## 15.2 封面：种子 + 按需 + 可淘汰缓存

```text
第 1 层  种子封面（几十张）   进 git，首页保底，永不失效
第 2 层  按需抓取 + 缓存      详情页触发，缓存有上限可淘汰
第 3 层  永不抓               没被访问过的长尾，零成本
```

**硬约束：列表页不能触发抓取**

```text
专辑列表页一次要 250 张图，并发抓取会打死 archive.org，
且用户要等几分钟才有图。

详情页（1 张）     → 按需抓，等 1-3 秒可接受
导入歌单（批量）   → 批量预热（用户主动操作，天然的预热时机）
专辑列表页（250）  → 只用已有的，没有就占位，【不抓】
```

**代价**

```text
封面从「静态资源」变成「后端服务」，多了一个运行时依赖
（archive.org 挂 / 代理断 / 限流都会变成线上错误路径）。
所以是【种子与按需并存】，不是替换。
```

---

## 15.3 繁简归一化：只在查询层扩，数据层不动

`traditional-chinese-policy` 规定「数据存繁体原样，转换放展示层」，
但在**搜索和导入**场景下会遇到硬问题：

```text
用户搜「周杰伦」  → 库里是「周杰倫」 → 等值查询搜不到
网易云给「周杰伦」→ 匹配不上「周杰倫」
```

**解法（不破坏事实层）**

```text
用户输入
   ↓
双向转换 t2s + s2t → 变体集合
   ↓
WHERE name IN ('周杰伦', '周杰倫')      ← 数据层一行不改
```

这套逻辑是**搜索 / 外部导入 / 音频匹配三处的共用件**，
在 Phase 1 的搜索里先沉淀。

---

## 15.4 ⚠️ 已知缺口：RAG 没有语料

Phase 2 的 RAG 需要**音乐知识文本**（乐评 / 百科 / 音乐史 / 艺人关系描述）。

**当前库里几乎没有**

```text
album.name / artist.name / track.name   ← 全是名字
artist.disambiguation                   ← 只有 5/263 个艺人有，且是短句
```

**没有乐评、没有百科、没有音乐史。**

**Phase 2 开工前必须先解决「语料从哪来」**

```text
MusicBrainz relationships  → 是结构化关系，不是可检索文本
Wikipedia API              → 有内容，但又是外部依赖，且中英混杂
LLM 生成                   → 会引入幻觉，污染事实层（违背「事实库」定位）
```

---

## 15.5 收藏的粒度

收藏的对象是**曲目**（`favorite_track.track_id`），首页展示的是**专辑**。
所以「从首页一键收藏」在语义上不成立，只能走两步：

```text
首页点专辑 → 专辑详情页 → 收藏曲目
```

若将来要「一键收藏整张专辑」，需新增 `favorite_album` 表，单独立项。

---

# 十六、最终项目目标

当 MusicMind 完成时，应该能够回答一个核心问题：

> **“我能不能独立设计、开发、调试和部署一个真正具备 Agent Workflow 的 AI 应用？”**

MusicMind 将作为这个问题的实践答案。

---

## 当前阶段

```text
Phase 0   项目定义            ✅ 已完成
Phase 1   基础业务骨架         ✅ 主体完成（剩余项已降级）
Phase 1.5 用户歌单导入         🔵 ③ 按需入库已完成，下一步 ④ 音频试听
Phase 2   音乐知识库 + RAG     ⬜ 未开始（前置：先解决 15.4 语料缺口）
```

**Phase 1 已完成**

```text
认证 ✅  收藏 ✅  Vue 3 前端 ✅  专辑列表/详情 ✅
歌单后端 ✅  繁简转换 ✅  封面管道 ✅  搜索 ✅  歌手页 ✅  MusicBrainz 查询 ✅
```

**Phase 1 剩余项已降级**（不是入口，做完导入再回头看）

```text
封面按需代理 · 歌单前端 · 播放记录 · 评分 · Redis · 首页策展
```

**Phase 1.5 的内部顺序**

```text
① 导入歌单        ✅
② 实体对齐        ✅ 难点已过（确定性匹配；繁简变体 + 空格归一，见本节上面）
③ 按需入库        ✅ 2026-09-30 完成
④ 音频试听        ⬜ 下一步
⑤ 音乐人格分析
⑥ 推荐
```
