#只负责请求MusicBrainz

import time
from typing import Any

import requests


class MusicBrainzClient:
    """
    MusicBrainz API 客户端。

    职责：
    1. 统一管理 API Base URL
    2. 统一管理 User-Agent
    3. 发送 HTTP 请求
    4. 处理 503 重试
    5. 控制请求频率

    不负责：
    - MusicMind 数据模型转换
    - 数据清洗
    - 数据入库
    """

    BASE_URL = "https://musicbrainz.org/ws/2"

    def __init__(
        self,
        user_agent: str,
        min_interval: float = 1.0,
        timeout: int = 10,
        max_retries: int = 3,
    ):
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        })

        self._last_request_time = 0.0

    def _wait_for_rate_limit(self):
        """
        控制请求频率。

        MusicBrainz 要求客户端不要超过平均 1 请求/秒。
        """
        elapsed = time.monotonic() - self._last_request_time

        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        发送 HTTP 请求并返回 JSON。
        """

        url = f"{self.BASE_URL}/{path.lstrip('/')}"

        for attempt in range(self.max_retries):
            self._wait_for_rate_limit()

            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    timeout=self.timeout,
                )

                self._last_request_time = time.monotonic()

                if response.status_code == 503:
                    if attempt < self.max_retries - 1:
                        wait_seconds = 2 ** attempt

                        print(
                            f"MusicBrainz 返回 503，"
                            f"{wait_seconds} 秒后进行第 {attempt + 2} 次尝试..."
                        )

                        time.sleep(wait_seconds)
                        continue

                    raise RuntimeError(
                        "MusicBrainz 连续多次返回 503，请稍后再试。"
                    )

                response.raise_for_status()

                return response.json()

            except requests.RequestException as e:
                if attempt < self.max_retries - 1:
                    wait_seconds = 2 ** attempt

                    print(
                        f"MusicBrainz 请求失败：{e}，"
                        f"{wait_seconds} 秒后重试..."
                    )

                    time.sleep(wait_seconds)
                    continue

                raise RuntimeError(
                    f"MusicBrainz 请求失败：{e}"
                ) from e

        raise RuntimeError("MusicBrainz 请求失败。")

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        GET 请求。
        """
        return self._request(
            method="GET",
            path=path,
            params=params,
        )

    def search_artist(
        self,
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        搜索 Artist。
        """
        return self.get(
            "/artist",
            params={
                "query": query,
                "limit": limit,
            },
        )

    def get_artist(
        self,
        artist_mbid: str,
    ) -> dict[str, Any]:
        """
        根据 MBID 获取 Artist。
        """
        return self.get(
            f"/artist/{artist_mbid}",
        )

    def get_artist_releases(
        self,
        artist_mbid: str,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        获取 Artist 关联的 Release。

        注意：
        MusicBrainz API 的 browse 支持分页。
        """
        return self.get(
            "/release",
            params={
                "artist": artist_mbid,
                "limit": limit,
                "offset": offset,
            },
        )

    def get_release(
        self,
        release_mbid: str,
    ) -> dict[str, Any]:
        """
        获取 Release 详情。

        同时请求：
        - recordings
        - release-groups
        - media
        - artist-credits
        """
        return self.get(
            f"/release/{release_mbid}",
            params={
                "inc": "recordings+release-groups+media+artist-credits",
            },
        )

    def get_release_group(
        self,
        release_group_mbid: str,
    ) -> dict[str, Any]:
        """
        获取 Release Group 详情。
        """
        return self.get(
            f"/release-group/{release_group_mbid}",
            params={
                "inc": "artist-credits",
            },
        )

    def get_recording(
        self,
        recording_mbid: str,
    ) -> dict[str, Any]:
        """
        获取 Recording 详情。
        """
        return self.get(
            f"/recording/{recording_mbid}",
            params={
                "inc": "artist-credits",
            },
        )