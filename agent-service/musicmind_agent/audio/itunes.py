"""iTunes Search：找 30 秒试听、下载、解码成波形。

【为什么用 iTunes】官方、合法、免费、不需要 key。实测 music.163.com 等国内
平台的播放地址要加密参数，而 iTunes 的 previewUrl 是直链。

【音频一个字都不存】下载到内存、解码到内存、算完特征就把波形丢掉 ——
全程不落盘。这是项目数据与存储原则里明确写的（音频只在播放时流式拉取）。
"""

from __future__ import annotations

import subprocess
import threading
import time
from functools import lru_cache

import imageio_ffmpeg
import numpy as np
import requests
from zhconv import convert

from musicmind_agent.config import ITUNES_MIN_INTERVAL, ITUNES_SEARCH_URL
from musicmind_agent.audio.features import SAMPLE_RATE

# 搜索接口限速约 20-25 请求/分。取 2.5 秒间隔留余量 ——
# 被限流时 iTunes 会直接返回空结果，看起来像「没有这首歌」，很难排查
_rate_lock = threading.Lock()
_last_request_at = 0.0

_ffmpeg_exe: str | None = None


def _throttle() -> None:
    global _last_request_at
    with _rate_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < ITUNES_MIN_INTERVAL:
            time.sleep(ITUNES_MIN_INTERVAL - elapsed)
        _last_request_at = time.monotonic()


def _ffmpeg() -> str:
    global _ffmpeg_exe
    if _ffmpeg_exe is None:
        _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    return _ffmpeg_exe


def normalize_name(text: str | None) -> str:
    """空格和大小写的差异不是差异。项目里其他地方（繁简、艺人比对）用的同一套思路。"""
    return (text or "").replace(" ", "").lower()


@lru_cache(maxsize=8192)
def name_variants(text: str) -> frozenset[str]:
    """一个名字的繁简变体集合。

    【为什么必须有这一层】我第一版忘了套这个，结果：
        库里「薛之谦」   iTunes「薛之謙」
        库里「凤毛麟角」 iTunes「鳳毛麟角」
        库里「素颜」    iTunes「素顏」
    全部匹配失败 —— 不是歌不对，是写法不同。这跟项目在
    MusicBrainz 实体对齐里遇到的是同一个问题、同一个解法：
    **数据层存原样，只在比对时把两边都扩成变体**。
    没套这一层时 393 首里只有 177 首核对得上（45%），其中
    薛之谦一人就有 102 首被误判成「艺人没核对上」。
    """
    base = normalize_name(text)
    if not base:
        return frozenset()
    out = {base}
    for target in ("zh-cn", "zh-tw"):
        converted = normalize_name(convert(text, target))
        if converted:
            out.add(converted)
    return frozenset(out)


def contains_name(haystack: str | None, needles: list[frozenset[str]]) -> bool:
    """haystack（的任一繁简变体）是否包含 needles 里任意一个变体。

    两边都要展开：只在一边转换是不够的（库里的「素颜」和 iTunes 的「素顏」
    互不包含，必须两边都转成同一批写法才有交集）。
    """
    hay_variants = name_variants(haystack or "")
    if not hay_variants:
        return False
    return any(
        needle in hay
        for needle_set in needles      # 每个 needle 是一个变体集合，要拆开
        for needle in needle_set
        for hay in hay_variants
    )


# 按顺序试的店铺。**顺序有讲究**，是实测定的：
#   · 默认（美国）店：西方歌全有，但中文歌覆盖差 ——
#     周杰倫《止戰之殤》《外婆》《珊瑚海》《愛在西元前》四首全无，返回的是
#     「感谢周杰伦」这种无关结果
#   · 台湾店：中文歌覆盖好得多（上面四首命中三首），**而且西方歌照样有**
#     （Coldplay / Ed Sheeran 实测都在）
#   · 但两边互补：薛之谦《演员》在台湾店没有、美国店有（存成 "Joker Xue"）
# 所以 tw 优先、默认兜底。代价是台湾店没有的歌要多花一次请求。
STOREFRONTS: tuple[str | None, ...] = ("tw", None)


def _search_once(
    title: str,
    artist: str,
    session: requests.Session,
    country: str | None,
    wanted_names: list[frozenset[str]],
    wanted_titles: frozenset[str],
) -> tuple[str | None, bool]:
    """查一个店铺。返回 (previewUrl 或 None, 艺人是否核对上)。"""
    _throttle()
    try:
        params = {"term": f"{title} {artist}", "media": "music", "entity": "song", "limit": 10}
        if country:
            params["country"] = country
        results = session.get(ITUNES_SEARCH_URL, params=params, timeout=20).json().get("results", [])
    except Exception:
        return None, False

    fallback: str | None = None

    for item in results:
        preview = item.get("previewUrl")
        if not preview:
            continue

        # 标题是硬条件：繁简任一写法命中即可。
        # 复用 contains_name 而不是再写一遍 —— 那边是子串匹配，
        # 直接对变体集合做 `in` 是集合成员判断，会漏掉「素顏 (with 何曼婷)」这种带后缀的
        if not contains_name(item.get("trackName"), [wanted_titles]):
            continue

        # 艺人是加分项，决定这条数据算不算「核对过」
        if contains_name(item.get("artistName"), wanted_names):
            return preview, True

        if fallback is None:
            fallback = preview

    return fallback, False


def search_preview(
    title: str,
    artist: str,
    session: requests.Session,
    aliases: tuple[str, ...] = (),
) -> tuple[str | None, bool]:
    """搜 30 秒试听。返回 (previewUrl 或 None, 艺人是否被验证过)。

    【为什么艺人只做「优先」不做「必须」】iTunes 里中文歌手存的是罗马字名 ——
    实测薛之谦是 "Joker Xue"、周杰倫是 "Jay Chou"。拿中文名去比 artistName
    会把结果全滤掉（我第一版就是这么写的，六首歌全部「无试听」）。所以：

      标题命中是硬条件（防止匹配到完全不相干的歌），
      艺人命中只用来在同名曲目里挑更可信的那个；
      一个都没命中时仍然返回第一条标题命中的，但【标记为艺人未验证】——
      调用方据此决定要不要采信，而不是让这条数据静默地混进去。

    传 aliases 能显著提高验证率：artist_alias 表里有罗马字名
    （周杰倫 → Jay Chou / Chieh-Lun Chou / ジェイ・チョウ）。
    """
    if not title or not artist:
        return None, False

    # 两边都展开成繁简变体再比 —— 见 name_variants 的说明
    wanted_names = [v for n in (artist, *aliases) if n for v in [name_variants(n)] if v]
    wanted_titles = name_variants(title)

    for country in STOREFRONTS:
        preview, verified = _search_once(
            title, artist, session, country, wanted_names, wanted_titles)
        if preview:
            return preview, verified

    return None, False


def fetch_waveform(preview_url: str, session: requests.Session) -> tuple[np.ndarray, str | None]:
    """下载并解码成单声道 float32 波形。返回 (波形, 错误原因)。

    【为什么要过一道 ffmpeg】iTunes 给的是 M4A/AAC，libsndfile 读不了
    （实测报 "Format not recognised"）。imageio-ffmpeg 自带二进制，
    不需要系统装 ffmpeg，也不用落盘中转 —— 走管道直接拿 PCM。
    """
    try:
        audio = session.get(preview_url, timeout=30).content
    except Exception as e:
        return np.zeros(0, dtype=np.float32), f"下载失败：{type(e).__name__}"

    if not audio:
        return np.zeros(0, dtype=np.float32), "下载到 0 字节"

    try:
        proc = subprocess.run(
            [
                _ffmpeg(), "-hide_banner", "-loglevel", "error",
                "-i", "pipe:0",
                "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE),
                "pipe:1",
            ],
            input=audio,
            capture_output=True,
        )
    except Exception as e:
        return np.zeros(0, dtype=np.float32), f"ffmpeg 起不来：{type(e).__name__}"

    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace")[:120]
        return np.zeros(0, dtype=np.float32), f"解码失败：{detail}"

    waveform = np.frombuffer(proc.stdout, dtype=np.float32)
    if waveform.size == 0:
        return waveform, "解码得到空波形"

    return waveform, None
