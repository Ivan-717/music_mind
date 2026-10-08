# M7.2 交接：30 秒试听

**这一步（Java 侧）是你的。** 目标：让曲目能试听 —— 数据（`preview_url`）早就在库里，
差一个接口和列表上的两个标记位。**前端我已经写完了**（见文末），你写完 Java 就能联调。

前置：无。数据、URL 可达性都已实测（见下）。

---

## 实测数据（都已验证过，不用再确认）

```
track_audio_feature.preview_url   418/418 全有值，全是 iTunes 30 秒预览
覆盖率（全库口径）                418 / 4617 首 ≈ 9%
覆盖率（「用户的歌」口径）         407 / 472 首 ≈ 86%   ← 试听真正服务的口径
URL 直连实测                      200 · 0.89s · 1MB · audio/x-m4p
                                  （浏览器直连 Apple，服务器不中转、带宽 0）
```

**为什么全库只有 9%**：`preview_url` 是 `analyze_tracks.py`（音频特征）的**副产物**，
而那个脚本设计上只处理「画像的输入」——用户歌单里已对齐的曲目 + 收藏的曲目，
**不处理推荐候选池**。全库其余 ~4200 首从没进过这个管道，这是正常的。

**想让新歌能有试听**：导入新歌单后跑一次
`cd agent-service && python analyze_tracks.py`
（断点续跑，算过的自动跳过，iTunes 限速约 2.5 秒/首）。

---

## 先说三条现实

### ① 九成的曲目没有试听 —— 靠 `hasPreview` 列提前表达

418/4617 是数据的现实，不是 bug。**没有试听源的曲目不该给 ▶ 按钮** ——
给一个播不了的按钮比不给更糟。所以列表接口要带 `hasPreview`，
前端 `v-if="t.hasPreview"` 过滤（前端侧已实现）。

### ② `preview_url` 会过期 —— 404 是正常答案

iTunes 的预览 URL 有有效期（`schema.sql` 的列注释里写了）。
界面上的 404 基本只有这一种来源，显示「试听暂时不可用」，**不自动重查**
（重查要再打 iTunes，而它有 20-25/分的限速）。

### ③ `track_audio_feature` 表在 Java 侧目前【零处使用】

所以三处都要新写：新 Mapper、两个 VO 加字段、两处 SQL 加一列。
新加一列这件事有一个坑要留意：`selectTracksByRelease` 有 `GROUP BY`，
如果 MySQL 报 `ONLY_FULL_GROUP_BY`，原因在这里（理论上 EXISTS 依赖的
`t.id` 在 GROUP BY 里，合法；真报错再说）。

---

## 你要写的（6 处）

### 1. `vo/PreviewVO.java` —— 新增

```java
package com.musicmind.vo;

/** 试听接口的返回体。就一个字段 —— 别为了"完整"塞别的 */
public record PreviewVO(String url) {}
```

### 2. `mapper/TrackAudioFeatureMapper.java` —— 新增

```java
package com.musicmind.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface TrackAudioFeatureMapper {

    /** 没有记录 / 记录里 url 为空都返回 null，由 service 决定怎么表达 */
    @Select("SELECT preview_url FROM track_audio_feature WHERE track_id = #{trackId} LIMIT 1")
    String selectPreviewUrl(@Param("trackId") Long trackId);
}
```

### 3. `service/TrackService.java` —— 新增

```java
package com.musicmind.service;

import com.musicmind.exception.ApiException;
import com.musicmind.mapper.TrackAudioFeatureMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class TrackService {

    private final TrackAudioFeatureMapper trackAudioFeatureMapper;

    /**
     * 30 秒试听的 URL。
     *
     * 「这首没有试听」在数据上完全正常（九成的歌都没有），但接口语义上
     * 用 404 表达 —— 前端把 404 显示成「试听暂时不可用」，和「URL 过期」
     * 走同一个兜底，不需要区分（都是「现在放不了」）。
     */
    public String previewUrl(Long trackId) {
        String url = trackAudioFeatureMapper.selectPreviewUrl(trackId);
        if (url == null || url.isBlank()) {
            throw new ApiException(404, "这首曲目没有试听");
        }
        return url;
    }
}
```

### 4. `controller/TrackController.java` —— 新增

```java
package com.musicmind.controller;

import com.musicmind.service.TrackService;
import com.musicmind.vo.PreviewVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/tracks")
@RequiredArgsConstructor
public class TrackController {

    private final TrackService trackService;

    /** SecurityConfig 是 anyRequest().authenticated()，这里自动要登录，不用改配置 */
    @GetMapping("/{id}/preview")
    public PreviewVO preview(@PathVariable Long id) {
        return new PreviewVO(trackService.previewUrl(id));
    }
}
```

### 5. 专辑曲目带 `hasPreview` —— 改两处

`vo/AlbumTrackVO.java` 加一个字段：

```java
    /** 有没有 30 秒试听（track_audio_feature.preview_url）。前端据此决定给不给 ▶ */
    private Boolean hasPreview;
```

`mapper/AlbumMapper.java` 的 `selectTracksByRelease`，SELECT 列表里
`artist_names` 之后加一行（其他原样不动）：

```java
    @Select("""
            SELECT rt.track_number,
                   rt.disc_number,
                   t.id          AS track_id,
                   t.name        AS name,
                   t.duration_ms AS duration_ms,
                   GROUP_CONCAT(
                       CONCAT(COALESCE(ta.credited_name, ar.name),
                              COALESCE(ta.join_phrase, ''))
                       ORDER BY ta.id SEPARATOR ''
                   ) AS artist_names,
                   EXISTS(SELECT 1 FROM track_audio_feature f
                          WHERE f.track_id = t.id
                            AND f.preview_url IS NOT NULL
                            AND f.preview_url <> '') AS has_preview
            FROM release_track rt
            JOIN track t              ON t.id = rt.track_id
            LEFT JOIN track_artist ta ON ta.track_id = t.id
            LEFT JOIN artist ar       ON ar.id = ta.artist_id
            WHERE rt.release_id = #{releaseId}
            GROUP BY rt.id, rt.track_number, rt.disc_number, t.id, t.name, t.duration_ms
            ORDER BY rt.disc_number, rt.track_number
            """)
    List<AlbumTrackVO> selectTracksByRelease(@Param("releaseId") Long releaseId);
```

> 别名写 `has_preview`（下划线）就行 —— MyBatis 的 mapUnderscoreToCamelCase
> 会映射到 `hasPreview`，和这份 SQL 里 `track_id` / `artist_names` 同一个路子。

### 6. 歌单曲目带 `hasPreview` —— 同上一套

`vo/ImportedTrackVO.java` 加字段（和 `matchedTrackId` 挨着，语义上它是它的补充）：

```java
    /** 有没有 30 秒试听。未对齐（matchedTrackId 为 null）的行恒为 false */
    private Boolean hasPreview;
```

`mapper/UserPlaylistMapper.java` 的 `selectTracks`，SELECT 列表里
`favorited` 之后加一行：

```java
    @Select("""
            <script>
            SELECT u.id, u.external_id, u.position, u.title, u.artists, u.album_name,
                   u.duration_ms, u.cover_url, u.match_status, u.matched_track_id,
                   (ft.id IS NOT NULL) AS favorited,
                   EXISTS(SELECT 1 FROM track_audio_feature f
                          WHERE f.track_id = u.matched_track_id
                            AND f.preview_url IS NOT NULL
                            AND f.preview_url &lt;&gt; '') AS has_preview
            FROM user_playlist_track u
            LEFT JOIN favorite_track ft
                   ON ft.user_id = u.user_id AND ft.track_id = u.matched_track_id
            WHERE u.import_id = #{importId} AND u.user_removed = 0
            <if test="filter == 'matched'">AND u.match_status = 'MATCHED'</if>
            <if test="filter == 'unmatched'">AND u.match_status &lt;&gt; 'MATCHED'</if>
            ORDER BY u.position
            LIMIT #{offset}, #{size}
            </script>
            """)
    List<ImportedTrackVO> selectTracks(@Param("importId") Long importId,
                                       @Param("offset") int offset,
                                       @Param("size") int size,
                                       @Param("filter") String filter);
```

> 未对齐的行 `u.matched_track_id` 是 NULL → `EXISTS` 对 NULL 返回 false → `has_preview = 0`，
> 正好是设计要的「没对齐就没有按钮」，不用额外条件。
>
> ⚠️ **`&lt;&gt;` 是故意的，不是笔误**：这段 SQL 在 `<script>` 标签里，MyBatis 会
> **先把它当 XML 解析** —— `<` 是 XML 的非法字符，直接写 `<>` 会在**启动时**就炸：
> `SAXParseException: 元素内容必须由格式正确的字符数据或标记组成`。
> 文件里 `filter` 那两行的 `&lt;&gt;` 就是这个原因。
> **判据**：带 `<script>` 的要转义；不带 `<script>` 的纯 `@Select`
> （比如 AlbumMapper 那条）不受影响，`<>` 直接写。

---

## 自测（写完先自己跑一遍）

```bash
# 编译 + 重启后端后：
TOKEN=$(curl -s localhost:8080/api/auth/login -H "Content-Type: application/json" \
  -d '{"username":"<你的账号>","password":"<密码>"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# ① track 8 是「止戰之殤」，有 preview
curl -s localhost:8080/api/tracks/8/preview -H "Authorization: Bearer $TOKEN"
# 期望：{"url":"https://audio-ssl.itunes.apple.com/..."}

# ② track 1 没有 preview
curl -s -o /dev/null -w "%{http_code}\n" localhost:8080/api/tracks/1/preview -H "Authorization: Bearer $TOKEN"
# 期望：404

# ③ 专辑曲目带标记。专辑 10（2004無與倫比演唱會）的 release 7 里
#    有 2 首带 preview（track 8 是其一），正好一半 true 一半 false
curl -s "localhost:8080/api/albums/10/tracks?releaseId=7" -H "Authorization: Bearer $TOKEN" | head -c 400
# 期望：每行里有 "hasPreview": true/false

# ④ 歌单曲目带标记（对齐过的曲目里应该能看到 true）
curl -s "localhost:8080/api/import/playlists/<importId>/tracks?page=1&size=20" -H "Authorization: Bearer $TOKEN" | head -c 400
```

---

## 前端已经写好的（不用你动）

```
frontend/src/api/track.js            GET /tracks/{id}/preview
frontend/src/stores/player.js        全局播放器（audio 在 store 里，切页面不断）
frontend/src/components/MiniPlayer.vue  底部播放条（琥珀进度线 + 播放键 + 时间 + 关闭）
frontend/src/App.vue                 挂载 + 内容让位（main.has-player）
AlbumDetailView / MyPlaylistView     行内 ▶（v-if="t.hasPreview"）+ 播放中行高亮
```

**降级已经验证过**：你的字段没加之前，按钮正确隐藏、页面零报错。

## 联调验收（Java 好了叫我来跑）

```
1. 专辑详情点 ▶ 出声，播放条滑入
2. 切到别的页面音乐不断
3. 没有 hasPreview 的曲目【没有】▶
4. 播完（30 秒）自动停
5. hasPreview=true 的抽 10 首，逐条验证真能播
6. 越权 / 不存在的 trackId → 404
```
