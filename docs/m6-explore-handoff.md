# M6 交接：音乐探索路径

**这一步是你的。** 目标：用户说「我想从 Oasis 开始了解 Britpop」，
Agent 给出一条**可点击的路径**，而不是一段散文。

对应 `project.md` §4.4，是六个核心功能里的最后一个。

---

## 起点：这一步**不需要新的数据能力**

```
音乐背景      search_knowledge（M5.4，13,189 块语料）  ← 有了
代表作品      search_upstream（M3，MusicBrainz）      ← 有了
本地有没有    库查询                                  ← 有了
抓进库里      /api/agent/fetch（M3）                  ← 有了
```

**缺的只是「形状」**：现在这些工具的输出被模型揉成一段话，
而 §4.4 要的是一条**有顺序、有关系、每一站能单独操作**的链路。

所以 M6 的工作量主要在**输出结构 + 前端渲染**，不在数据。

---

## 设计：`chat` 多输出一个 `path`

```json
{
  "answer": "……",
  "recommendations": [],
  "fetch_proposals": [],
  "path": {
    "topic": "Britpop",
    "steps": [
      {"order": 1, "name": "Oasis", "kind": "artist",
       "release_mbid": "52f3b1d2-…", "in_library": false,
       "why_here": "从这里开始：他们是最容易被听进去的入口",
       "relation": null},
      {"order": 2, "name": "Blur", "kind": "artist",
       "release_mbid": "b1c9…", "in_library": true,
       "why_here": "对位面",
       "relation": "1995 年那场「榜单之战」的另一方 —— 这段对立本身就是 Britpop 的故事"},
      {"order": 6, "name": "Britpop", "kind": "genre",
       "release_mbid": null, "in_library": true,
       "why_here": "终点：回到这个运动本身",
       "relation": "前面五站都是它的切面"}
    ]
  }
}
```

**每一站能单独操作**：有 `release_mbid` 的可以「抓进库里」，
没有的（流派那站）点进去就是语料里的介绍。

---

## 两条机械防线

### ① 路径里的名字，必须来自**工具真返回过**的内容

模型对音乐史很熟。你让它「从 Oasis 讲 Britpop」，它会顺手写上
Pulp、Suede、Supergrass —— 而**那些名字它根本没查过**，是脑子里的。

这和 M3 的 `fetch_proposals` 是同一个问题（也是同一条解法）：
**只认工具真返回过的名字，不在名单里的直接丢。**

```python
def _resolve_path(raw, knowledge_names, upstream_names, connection) -> dict | None:
    """把模型给的路径解析成一条可渲染的链路。

    **每一站的名字必须在 allowed 里** —— 语料的条目名，或 MusicBrainz 搜到的
    艺人/专辑名。模型脑子里那些没查过的名字会被丢掉。

    【这条防线保证什么、不保证什么】它保证「你说的每一站都有出处」，
    **不保证「关系是真的」** —— 「Blur 是 Oasis 的对位面」这句话对不对，
    机器判不了。这一点要写进 limitations。
    """
```

### ② `in_library` **由代码填**，不由模型填

模型不知道库里有什么。让它填，它会猜。

```python
def _in_library(connection, name: str, kind: str) -> bool:
    with connection.cursor() as cursor:
        table, column = ("artist", "name") if kind == "artist" else ("genre", "name")
        cursor.execute(
            f"SELECT 1 FROM {table} WHERE name = %s "
            f"OR REPLACE(name, ' ', '') = REPLACE(%s, ' ', '') LIMIT 1",
            (name, name))
        return cursor.fetchone() is not None
```

`REPLACE(name,' ','')` 是因为库里存的是 MusicBrainz 的名字
（「G.E.M. 鄧紫棋」），模型可能写「G.E.M.邓紫棋」。

---

## 你要写的（3 处）

### 1. `tools/knowledge.py` 的 rows 里加一个「名称」字段

路径解析要拿名字去对，而现在名字埋在 `来源` 里：

```python
        rows=[{
            # 【单独给一列】路径解析要拿它去对「模型提到的名字有没有出处」。
            # 埋在「来源」那串里的话就得解析字符串 —— 那种解析迟早会被格式改动打脸
            "名称": h["name"],
            "类型": h["kind"],
            "来源": f"{h['kind']}／{h['page_title']}（{h['lang']}）",
            "相似度": h["score"],
            "正文": h["text"][:600] + ("…" if len(h["text"]) > 600 else ""),
        } for h in hits],
```

### 2. `chat.py` — 三处改动

**a. `CHAT_SYSTEM` 的「直接回答」加一个字段**

```
{"answer": "…", "recommendations": [...], "fetch_proposals": [...], "path": {...}}
```

并在规则里补：

```
- **用户说「我想了解 X」「从 X 开始」「带我入门」这类，给一条路径，不要只写一段话。**
  先用 `search_knowledge` 查这个主题（它是什么、有哪些代表艺人），
  必要时用 `search_upstream` 找代表专辑。

  path 的形状：
    {"topic": "主题名",
     "steps": [{"order": 1, "name": "艺人或流派名", "kind": "artist|genre",
                "release_mbid": "要抓就填，search_upstream 返回过的那张；没有就 null",
                "why_here": "为什么这一站在这里",
                "relation": "和上一站的关系；第一站填 null"}]}

  **3-6 站**。最后一站通常是那个流派/运动本身（kind=genre）。

  **每一站的 name 必须是你这次真的查过的** —— 语料条目里出现过的，
  或者 search_upstream 返回过的。**不要写你没查过的名字**，
  哪怕你很确定它属于这个流派：没查过就没有出处，会被丢掉。
```

**b. `chat()` 里攒名字，加解析**

```python
    knowledge_names: set[str] = set()
    upstream_names: set[str] = set()
    ...
            if name == "search_knowledge":
                knowledge_names |= {str(r.get("名称")) for r in result.rows if r.get("名称")}
            if name == "search_upstream":
                upstream_names |= {str(r.get("artist")) for r in result.rows if r.get("artist")}
                upstream_names |= {str(r.get("title")) for r in result.rows if r.get("title")}
```

**c. 返回值和 `_resolve_path`**

```python
                "path": _resolve_path(raw.get("path"), knowledge_names,
                                      upstream_names, ctx.connection, ctx.facts),
```

```python
MAX_PATH_STEPS = 6


def _resolve_path(raw, knowledge_names: set[str], upstream_names: set[str],
                  connection, facts: dict) -> dict | None:
    """把模型给的路径解析成一条可渲染的链路。没给就返回 None。

    **每一站的名字必须在 allowed 里**（语料条目名 / MusicBrainz 搜到的名）。
    模型对音乐史很熟，会顺手写没查过的名字 —— 那些是它脑子里的，
    不是这个系统的数据。

    【这条防线保证什么】「你说的每一站都有出处」。
    【不保证什么】「关系是真的」——「Blur 是 Oasis 的对位面」对不对，
    机器判不了。所以 path 要进 limitations 那一档。
    """
    if not raw or not isinstance(raw, dict):
        return None

    from musicmind_agent.validate.normalize import name_matches

    allowed = knowledge_names | upstream_names

    def known(name: str) -> bool:
        return any(name_matches(name, n) or name_matches(n, name) for n in allowed)

    steps = []
    for item in (raw.get("steps") or [])[:MAX_PATH_STEPS]:
        name = (item.get("name") or "").strip()
        if not name or not known(name):
            continue          # 没出处的直接丢，不猜
        kind = item.get("kind") if item.get("kind") in ("artist", "genre") else "artist"
        steps.append({
            "order": len(steps) + 1,           # 丢过站之后重排，不留空号
            "name": name,
            "kind": kind,
            "release_mbid": item.get("release_mbid") or None,
            "in_library": _in_library(connection, name, kind),
            # 【也要过 render_text】和 reason / why 同一条规矩，少一处
            # 就会漏出没渲染的 {fact.key} —— M3 在 why 上栽过一次
            "why_here": render_text(item.get("why_here") or "", facts, strict=False),
            "relation": render_text(item.get("relation") or "", facts, strict=False) or None,
        })

    if len(steps) < 2:
        return None           # 一站的「路径」没有意义
    return {"topic": raw.get("topic") or steps[-1]["name"], "steps": steps}
```

**`why_here` / `relation` 也要过 `render_text`** —— 和 `reason`、`why` 同一条规矩，
少一处就会出现没渲染的 `{fact.key}`（M3 在 `why` 上栽过一次）。

### 3. 前端：`ExploreView.vue` 渲染路径

一条竖排的链路，每站一个小卡：

```
● 1  Oasis                    [抓进库里]
│    从这里开始：他们是最容易被听进去的入口
│
● 2  Blur              ✓已有
│    1995 年那场「榜单之战」的另一方 —— 这段对立本身就是 Britpop 的故事
│
● 6  Britpop           ✓已有
     终点：回到这个运动本身
```

**要点**：
- `in_library` 为真时显示「已有」，不显示抓取按钮（不用重复抓）
- 有 `release_mbid` 才显示「抓进库里」，复用 M3 的 `apiFetchUpstream`
- 关系（`relation`）写在两站之间，不是站内 —— 它是**边**不是**点**

---

## 验收

```
1. 问「我想从 Oasis 开始了解 Britpop」→ 给出 path，3-6 站
2. **每一站的 name 都在 [语料条目名 + MB 搜索结果] 里**（没出处的被丢掉）
3. in_library 和库里实际对得上（抽一站手工核）
4. 有 release_mbid 的站能点「抓进库里」，且落进「AI 帮你找的」
5. why_here / relation 里没有未渲染的 {占位符}
6. 问「我听得最多的是什么流派」→ 不给 path（那不是探索型问题）
7. 只写了一站的话 path 返回 null，不渲染（一站的路径没有意义）
```

**第 2 条是这一步的核心。** 第 6 条是反向的：别让任何问题都长出路径来。

---

## 诚实的边界（要写进 limitations）

```
路径的「顺序」和「关系」是模型组织的，机器只能保证每站有出处 ——
「为什么是 Blur 第二站」这件事没有数据支撑，它是叙事，不是事实。
```

这和报告那边「LLM 负责好玩、代码负责真实」是同一条分工，
只是这里「好玩」的部分更大一些。
