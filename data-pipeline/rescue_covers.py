"""给 Cover Art Archive 没有的专辑补封面（iTunes → 网易云两级兜底）。

跑法：python rescue_covers.py [--limit N]
  · 只处理 manifest 里 status=no_cover 且没试过兜底源的专辑
  · 断点续跑：manifest 里打了 alt_tried 的跳过
  · 下载写 frontend/public/covers/{albumId}.jpg，manifest 改 status=ok

【为什么加这一层】97 张 no_cover 是 Cover Art Archive 的上游现实 —— 但
「上游 A 没有」不等于「哪儿都没有」：iTunes 的 Search API 按专辑名+艺人能搜到
artworkUrl（M7.2 的试听链路验证过它可达），网易云的封面在导入歌单时就抓过、
存在 user_playlist_track.cover_url 里。两级兜底都试过才算真的没有。

【限速】iTunes 约 20-25 请求/分 —— 每张专辑一次搜索 = 2.5 秒/张。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402
import zhconv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from database.connection import get_connection  # noqa: E402

COVER_DIR = Path(__file__).resolve().parents[1] / "frontend" / "public" / "covers"
MANIFEST = COVER_DIR / "_manifest.json"
ITUNES_SLEEP = 2.5      # 20-25 请求/分的硬约束


def normalize(s: str) -> str:
    """够用的归一：小写、去空格、剥括号副题。两边都做才有效。"""
    s = (s or "").lower().replace(" ", "")
    for ch in ("(", "（"):
        i = s.find(ch)
        if i > 0:
            s = s[:i]
    return s


def search_itunes(album: str, artist: str, session) -> str | None:
    """iTunes 搜专辑封面。返回 600x600 的 URL，没有就 None。

    命中判据：collectionName 归一后等于/包含专辑名归一 —— iTunes 的搜索结果
    和 MusicBrainz 的名字经常差一个括号副题，normalize 两边都剥。
    """
    term = f"{album} {artist}"
    try:
        # 【country=tw 不是可选项】默认是美国店 —— 中文专辑基本搜不到。
        # 台湾店华语覆盖好，西方专辑也在（实测：搜周杰伦直接出结果）
        r = session.get("https://itunes.apple.com/search",
                        params={"term": term, "entity": "album",
                                "limit": 5, "country": "tw"},
                        timeout=15)
        r.raise_for_status()
        items = r.json().get("results", [])
    except Exception as e:
        print(f"    iTunes 查询失败：{type(e).__name__}")
        return None

    # 两边繁简都归一再比（「尋找周杰倫」 vs 「寻找周杰伦」）
    want = normalize(zhconv.convert(album, "zh-cn"))
    for it in items:
        got = normalize(zhconv.convert(it.get("collectionName") or "", "zh-cn"))
        if got and want and (got == want or want in got or got in want):
            url = it.get("artworkUrl100") or ""
            if url:
                return url.replace("/100x100bb", "/600x600bb")
    return None


def netease_cover(connection, album_name: str) -> str | None:
    """从导入歌单里同一专辑名抓过的平台封面兜底（当时存下来的现成字段）。

    【库里存的是简体】歌单来自网易云/QQ，专辑名是简体；而 MusicBrainz 那侧
    多半是繁体（「尋找周杰倫」）—— 不转就永远查不上（这个仓库的老坑）。
    """
    simplified = zhconv.convert(album_name, "zh-cn")
    with connection.cursor() as cur:
        cur.execute(
            """SELECT cover_url FROM user_playlist_track
               WHERE (album_name = %s OR album_name = %s)
                 AND cover_url IS NOT NULL AND cover_url <> ''
               LIMIT 1""", (album_name, simplified))
        row = cur.fetchone()
    return row["cover_url"] if row else None


def load_targets(connection, manifest: dict, limit: int | None) -> list[dict]:
    """目标 = **库里所有没有封面文件**的专辑，不是「manifest 里标了 no_cover 的」。

    【为什么必须这样】manifest 是 M0 时代全量抓完建的快照 —— 那之后
    按需入库的新专辑**根本不在里面**，老逻辑（只看 manifest 的 no_cover）
    会把它们整批漏掉。实测林俊杰 12 张里 8 张没封面（《第二天堂》《乐行者》
    《编号89757》全在），就是这么漏的。
    文件（frontend/public/covers/{id}.jpg）才是唯一真相。
    alt_tried 的断点保留 —— 两个源都试过没有的，不重复跑。
    """
    with connection.cursor() as cur:
        cur.execute("SELECT id, name FROM album")
        albums = cur.fetchall()
    ids = [a["id"] for a in albums
           if not (COVER_DIR / f"{a['id']}.jpg").exists()
           and not manifest.get(str(a["id"]), {}).get("alt_tried")]
    if limit:
        ids = ids[:limit]
    if not ids:
        return []
    fmt = ",".join(str(i) for i in ids)
    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT al.id AS album_id, al.name AS album_name,
                   (SELECT ar.name FROM release_track rt
                      JOIN music_release mr ON mr.id = rt.release_id
                      JOIN track_artist ta ON ta.id = (
                           SELECT MIN(ta2.id) FROM track_artist ta2
                            WHERE ta2.track_id = rt.track_id)
                      JOIN artist ar ON ar.id = ta.artist_id
                    WHERE mr.album_id = al.id LIMIT 1) AS artist_name
            FROM album al WHERE al.id IN ({fmt})""")
        return cur.fetchall()


def compress_covers(max_kb: int = 200, size: int = 600) -> int:
    """把硬盘上的封面统一压到 size×size JPEG。

    【为什么必须做】网易云兜底抓回来的是原图（实测有 6.2MB 一张的）——
    covers/ 是进 git 的静态资源，指望「反正本地能加载」不行。
    iTunes 那边本来就是 600×600（几十 KB），只有大图会被动。
    """
    from PIL import Image

    total_before = total_after = 0
    n = 0
    for f in sorted(COVER_DIR.glob("*.jpg")):
        before = f.stat().st_size
        if before <= max_kb * 1024:
            continue
        im = Image.open(f).convert("RGB")
        im.thumbnail((size, size))
        im.save(f, "JPEG", quality=85, optimize=True)
        after = f.stat().st_size
        total_before += before
        total_after += after
        n += 1
        print(f"  {f.name}: {before // 1024}KB → {after // 1024}KB")
    print(f"压缩 {n} 张：{total_before / 1e6:.1f}MB → {total_after / 1e6:.1f}MB")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--compress", action="store_true",
                        help="只做压缩：把 covers 里 >200KB 的缩到 600px JPEG q85")
    args = parser.parse_args()

    if args.compress:
        return compress_covers()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    connection = get_connection()
    session = requests.Session()
    session.headers.update({"User-Agent": "MusicMind/0.1"})

    targets = load_targets(connection, manifest, args.limit)
    print(f"可补的 no_cover 专辑：{len(targets)} 张（已试过兜底的跳过）")

    itunes_ok = netease_ok = 0
    for i, t in enumerate(targets, 1):
        album, artist = t["album_name"], t["artist_name"] or ""
        url = search_itunes(album, artist, session)
        source = "itunes"
        if not url:
            url = netease_cover(connection, album)
            source = "netease"

        if not url:
            manifest.setdefault(str(t["album_id"]),
                                 {"release_mbid": None, "status": "no_cover"})["alt_tried"] = True
            print(f"  [{i}/{len(targets)}] {album[:24]} —— 两个源都没有")
            time.sleep(ITUNES_SLEEP)
            continue

        try:
            blob = session.get(url, timeout=20).content
            if len(blob) < 1000:
                raise ValueError(f"内容太小（{len(blob)}B）")
            (COVER_DIR / f"{t['album_id']}.jpg").write_bytes(blob)
            manifest[str(t["album_id"])] = {
                "release_mbid": None, "status": "ok",
                "alt_source": source,          # 记录来路，好核对 / 好回滚
            }
            if source == "itunes":
                itunes_ok += 1
            else:
                netease_ok += 1
            print(f"  [{i}/{len(targets)}] {album[:24]} ← {source} ✓ ({len(blob)//1024}KB)")
        except Exception as e:
            manifest.setdefault(str(t["album_id"]),
                                 {"release_mbid": None, "status": "no_cover"})["alt_tried"] = True
            print(f"  [{i}/{len(targets)}] {album[:24]} 下载失败：{type(e).__name__}")

        if source == "itunes":
            time.sleep(ITUNES_SLEEP)

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    connection.close()
    print(f"\n补回 {itunes_ok + netease_ok} 张（iTunes {itunes_ok} / 网易云 {netease_ok}）")
    print(f"manifest 已更新：{MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
