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
TypeScript
Vite
ECharts
```

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
```

技术：

```text
Vue 3
Spring Boot
MySQL
Redis
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

# 十五、最终项目目标

当 MusicMind 完成时，应该能够回答一个核心问题：

> **“我能不能独立设计、开发、调试和部署一个真正具备 Agent Workflow 的 AI 应用？”**

MusicMind 将作为这个问题的实践答案。

---

## 当前阶段

**Phase 0：项目定义 —— 已完成**

下一阶段：

**Phase 1：基础音乐业务系统设计**

重点确定：

```text
用户有哪些功能？
有哪些核心数据？
有哪些页面？
数据库有哪些核心表？
一次完整的用户操作如何流转？
第一版 MVP 到底做到什么程度？
```
