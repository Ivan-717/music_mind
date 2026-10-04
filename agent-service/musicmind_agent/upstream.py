"""MusicBrainz 查询。**只读上游，不写任何本地表、不排队。**

【和 data-pipeline 那个 client 的关系】那个在另一个 venv 里，import 不过来，
而且它是给批量导入用的（有增量同步、entity 解析那一堆）。
这里只要一件事：**按几个条件搜 release，返回够组一张歌单的候选**。

【限速 1 请求/秒是硬要求】MusicBrainz 对匿名调用是 1 req/s，
超了会被封（他们的 User-Agent 政策要求带上联系方式）。
这个类自己 sleep，不指望调用方守规矩 —— 和 CoverArtClient 同一个形状。

【为什么是结构化参数，不是让模型写查询串】MB 的查询是 Lucene 语法
（`release:xxx AND artist:yyy`），让模型自由发挥等于让它拼一个可能语法错的串，
而错误信息是 400，看起来像我们的 bug。参数在这里拼，模型只填值。
"""

from __future__ import annotations

import time

import requests

# 【User-Agent 从 config 拿，别在这儿写一个】
# .env 里的 MUSICBRAINZ_USER_AGENT 是**三边共用**的：Java 的 application.yaml、
# data-pipeline 的 config/settings.py、还有这里。
# 而且**绝对不能编一个假 URL 当兜底** —— MusicBrainz 的 UA 政策要求带真实联系方式，
# 他们据此联系你。编一个不存在的地址比留空更糟，2026 年会因此被限流甚至封
from musicmind_agent.config import MUSICBRAINZ_API, MUSICBRAINZ_USER_AGENT

MB_BASE = MUSICBRAINZ_API
USER_AGENT = MUSICBRAINZ_USER_AGENT
MIN_INTERVAL = 1.0


class UpstreamError(Exception):
    pass


class MusicBrainzSearch:
    def __init__(self, timeout: int = 20, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        # trust_env 默认 True，会读 .env 里的 HTTPS_PROXY（config 那边 load_dotenv 过了）
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last = 0.0

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(self.max_retries + 1):
            self._wait()
            try:
                resp = self.session.get(f"{MB_BASE}{path}", params=params,
                                        timeout=self.timeout)
                self._last = time.monotonic()
            except Exception as e:
                if attempt == self.max_retries:
                    raise UpstreamError(f"{type(e).__name__}: {e}") from e
                time.sleep(2 * (attempt + 1))
                continue

            if resp.status_code == 503:
                # MB 忙的时候会 503，等一会儿重试是官方建议
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise UpstreamError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        raise UpstreamError("重试完了还是失败")

    def search_releases(self, *, artist: str | None = None,
                        release: str | None = None,
                        tag: str | None = None,
                        year_from: int | None = None,
                        year_to: int | None = None,
                        limit: int = 8) -> list[dict]:
        """按条件搜 release。返回够给用户挑的一小把。

        **至少要给一个条件** —— 无条件搜索等于「随便给我几张专辑」，
        那对用户没有意义，而且会白白吃掉限速配额。
        """
        parts = []
        if release:
            parts.append(f'release:"{release}"')
        if artist:
            parts.append(f'artist:"{artist}"')
        if tag:
            # tag 在 MB 上是社区打的，覆盖不均 —— 常见的流派基本都有，
            # 冷门的长尾可能空手而归。空了就如实说找不到
            parts.append(f'tag:"{tag}"')
        if year_from or year_to:
            lo = year_from or 1900
            hi = year_to or 2030
            parts.append(f"date:[{lo} TO {hi}]")

        if not parts:
            raise UpstreamError("至少要给一个搜索条件")

        data = self._get("/release", {
            "query": " AND ".join(parts),
            "fmt": "json",
            "limit": max(1, min(limit, 25)),
        })

        out = []
        for r in data.get("releases", []):
            credits = r.get("artist-credit") or []
            name = "".join(
                (c.get("name") or "") + (c.get("joinphrase") or "") for c in credits
            ).strip()
            date = r.get("date") or ""
            out.append({
                "release_mbid": r.get("id"),
                "title": r.get("title"),
                "artist": name or "未知",
                "year": date[:4] if date[:4].isdigit() else None,
                "primary_type": r.get("release-group", {}).get("primary-type"),
                "track_count": r.get("track-count"),
            })
        return out