# 只负责请求 Cover Art Archive

import time

import requests


class CoverArtClient:
    """
    Cover Art Archive 客户端。

    职责：
    1. 统一管理 Base URL
    2. 统一管理 User-Agent
    3. 控制请求频率
    4. 区分「这个 release 没有封面」(404) 和「请求失败」

    不负责：
    - 决定用哪个 release 的封面
    - 文件命名与落盘

    注意：coverartarchive.org 对封面文件是 307 跳转到 archive.org，
    requests 默认跟随重定向，所以代理配置必须对整个 session 生效。
    """

    BASE_URL = "https://coverartarchive.org"

    def __init__(
        self,
        user_agent: str,
        min_interval: float = 1.0,
        timeout: int = 20,
        max_retries: int = 3,
    ):
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries

        self.session = requests.Session()
        # trust_env 默认就是 True，会读 os.environ 里的
        # HTTPS_PROXY / HTTP_PROXY —— .env 经 load_dotenv 进来后自动生效
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "image/*",
        })

        self._last_request_time = 0.0

    def _wait_for_rate_limit(self):
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def fetch_front(self, release_mbid: str, size: int = 250) -> bytes | None:
        """
        取某个 release 的正面封面。

        返回：
            图片字节 —— 拿到了
            None     —— 这个 release 没有封面（404），不是错误

        抛异常：
            网络/代理问题、连续 5xx
        """
        url = f"{self.BASE_URL}/release/{release_mbid}/front-{size}"

        for attempt in range(self.max_retries):
            self._wait_for_rate_limit()

            try:
                response = self.session.get(url, timeout=self.timeout)

                self._last_request_time = time.monotonic()

                # 404 = 这个 release 没有封面。这是正常情况，不算失败。
                if response.status_code == 404:
                    return None

                if response.status_code == 503:
                    if attempt < self.max_retries - 1:
                        wait_seconds = 2 ** attempt
                        print(
                            f"    Cover Art Archive 返回 503，"
                            f"{wait_seconds} 秒后重试..."
                        )
                        time.sleep(wait_seconds)
                        continue
                    raise RuntimeError("Cover Art Archive 连续多次返回 503。")

                response.raise_for_status()

                return response.content

            except requests.RequestException as e:
                if attempt < self.max_retries - 1:
                    wait_seconds = 2 ** attempt
                    print(f"    封面请求失败：{e}，{wait_seconds} 秒后重试...")
                    time.sleep(wait_seconds)
                    continue
                raise RuntimeError(f"封面请求失败：{e}") from e

        raise RuntimeError("封面请求失败。")
