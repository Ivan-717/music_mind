"""封面文件的落盘位置，以及「按需补一张」。

【为什么要有这个模块】原来只有 fetch_covers.py 这个批处理脚本会写封面，
而按需入库（③）进来的新专辑没人管 —— 用户看到的是「从歌单导入的歌全都没封面」。

而这个故障**不会报错**：CoverImage 直接拼 `/covers/{albumId}.jpg`，
文件不在就 `@error` 退成占位块。看起来像「这个功能还没做」，
不像坏了 —— 所以它能一直躺在那儿没人发现。
"""

from __future__ import annotations

from pathlib import Path

# data-pipeline/cover/store.py -> cover/ -> data-pipeline/ -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]
COVER_DIR = PROJECT_ROOT / "frontend" / "public" / "covers"

# 和 fetch_covers.py 用同一档尺寸。两处不一致的话，批处理抓的和按需抓的
# 会一张清楚一张糊，而页面上分不出是谁抓的
COVER_SIZE = 250


def cover_path(album_id: int) -> Path:
    return COVER_DIR / f"{album_id}.jpg"


def save_cover(album_id: int, data: bytes) -> Path:
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    path = cover_path(album_id)
    path.write_bytes(data)
    return path


def ensure_cover(client, album_id: int, release_mbids: list[str],
                 size: int = COVER_SIZE, force: bool = False) -> str:
    """确保这张专辑的封面文件存在。返回一句状态描述，调用方拿去打日志。

    【它绝不抛异常】封面是锦上添花。抓不到就让整次入库判成失败的话，
    用户那一行会永远留着「未收录」—— 那个代价比「没封面」大得多。

    已有的文件直接跳过（force=True 才重下），和 fetch_covers.py 同一个口径：
    「有没有封面」是一个文件存不存在，不是一个数据库状态。
    """
    if not album_id or not release_mbids:
        return "没有 release，跳过"

    if cover_path(album_id).exists() and not force:
        return "已有封面，跳过"

    last_error = None
    for mbid in release_mbids:
        try:
            data = client.fetch_front(mbid, size=size)
        except Exception as e:
            # 记下来但继续试下一个 release —— 同一个专辑不同发行的封面
            # 是各自独立的，一个超时不代表别的也不行
            last_error = f"{type(e).__name__}: {e}"
            continue

        if data is None:
            continue          # 这个 release 没有封面（404），正常情况

        save_cover(album_id, data)
        return f"已抓取 {len(data)} 字节"

    if last_error:
        return f"全都没抓到（最后一次：{last_error}）"
    return "所有 release 都没有封面"
