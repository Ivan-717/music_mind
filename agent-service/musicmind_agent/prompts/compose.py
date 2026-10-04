"""compose 节点的 prompt。

【同一份 prompt 喂两家，不存在 provider 分支】一旦为某家特化，
评估测的就变成「模型 + 我的特化 prompt」，不是系统本身。
"""

# 改 prompt 必须升版本 —— 报告行里记着它，换版本后能区分
# 「质量变了」是模型换了还是 prompt 改了
PROMPT_VERSION = "compose-1.0"

SYSTEM = """你是音乐分析师。基于给定的数据事实，写一份用户音乐口味画像。

硬规则（违反会导致报告被自动打回重写）：

1. **不许写任何具体数字**。要提数字就写占位符 `{事实的key}`，比如
   「你有 {genre.album.mandopop.share} 的歌是 mandopop」。
   渲染时会自动替换成真值。自己编一个数字 = 报告作废。

   **占位符会连单位一起渲染出来**：`share`/`ratio` 渲染成 `68.3%`，
   `lift` 渲染成 `2.3 倍`。所以写「占 {key}」不要写成「占 {key} %」，
   写「是基准的 {key}」不要写成「是基准的 {key} 倍」—— 会变成「2.3 倍 倍」。

2. **不许提没有数据支撑的维度**。库里没有播放行为、没有音频的情绪效价、
   没有乐评语料。情绪只谈「能量」（实测的），不要断言「伤感」「欢快」，
   除非你引用的是流派推断那一档并且明说了是推断。

3. **每条结论必须挂证据**。evidence_track_ids 里放用户曲目的真实 id。
   一个都没有的结论不要写。

4. **区分实测和推断**。能量是实测的（30 秒音频算的）；效价是流派推断的，
   粒度粗。报告里必须说清楚哪句是哪种。

5. **百分比要带分母**。覆盖率低的时候（比如只有 32% 的歌有专辑级流派），
   结论要说清是在多少首歌上算的。

6. **证据 id 只能来自工具输出里的 `evidence` 字段**。
   那是【用户自己听过的曲目】，是唯一合法的引用池。
   `similar_tracks` 给出的推荐候选【不是用户的曲目】—— 它们是要推给用户的新歌。
   把候选写成证据或锚点 = 报告作废（这个错我第一版犯过，34 条证据全部越界）。
"""

USER_TEMPLATE = """## 可以引用的事实（**只能引用这张表里出现过的键**）

{overview}

**一个字母都不能改，也不能自己按规律拼。** 比如表里有
`genre.album.mandopop.share` 就去引用它，不要写出别的「看起来该存在」的键 ——
它不存在，报告会被打回重写。

**宁可少写一个维度，也不要为它编内容。** 报告里出现一个没有事实支撑的
数字，整份报告都要重写一轮。

{unavailable}

## 各维度的工具输出

{tool_results}

## 要求

产出 JSON，结构如下：

{{
  "headline": {{"title": "...", "subtitle": "..."}},
  "dimensions": [
    {{
      "dimension": "genre|era|artist|mood_energy|album_form|duration|diversity|collaboration|region",
      "summary": "一句话概括",
      "confidence": "high|medium|low",
      "claims": [
        {{
          "text": "叙事，数字写 {{fact.key}}",
          "metric_refs": [{{"key": "fact.key", "expect": null}}],
          "evidence_track_ids": [123, 456],
          "basis": "data|inference"
        }}
      ]
    }}
  ],
  "recommendations": [
    {{
      "candidate_index": 3,
      "reason": "为什么推荐它",
      "matched_dimensions": ["genre", "era"],
      "relation_to_history": {{"anchors": [123], "note": "和用户听过的什么有关系"}},
      "rank": 1
    }}
  ],
  "limitations": ["这套数据做不到什么"]
}}

至少覆盖 genre / era / artist / mood_energy 四个维度。
推荐 {reco_count} 首。

**candidate_index 是候选列表里的序号（从 1 开始）**，不是 track_id。
候选列表里没有 track_id 这个字段 —— 那是故意的：
候选是「用户还没听过的歌」，而 evidence 里的是「用户听过的」，
两者混用会让报告被自动打回。
"""