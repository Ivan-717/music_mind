"""给「已对齐但 iTunes 没有试听」的歌补网易云试听。

跑法：python rescue_previews.py [--limit N]

【覆盖谁】导入歌单里已对齐、但 iTunes（台湾店+美国店）搜不到试听的歌 ——
映射是现成的：user_playlist_track.external_id（网易云 song id）↔ matched_track_id。

【怎么存】写 track_audio_feature 一行「只有 URL 没有特征」的记录
（arousal_measured=NULL，analyzer_version='netease-fallback'）。
Java 侧四处 has_preview 的 EXISTS 都只看 preview_url，自动生效；
能量统计的读方全部判空，NULL 不会混进均值。
副作用：这会占住 analyze_tracks 的 already_done（这首不再跑特征分析）——
将来 iTunes 上架了想补，用 --reanalyze 强制。

【VIP 歌】匿名请求 outer/url 对 VIP/版权受限的歌返回 404 ——
那是网易云对「未登录请求」的策略（App 里能听是因为你有登录态）。
想覆盖 VIP 歌：在项目根 .env 加一行
    NETEASE_COOKIE=<网页版登录后的 cookie>
本脚本会自动带上（没有就匿名跑，只是少救一批）。
**cookie 是敏感凭证**：不提交、会过期、过期了重新从浏览器拿一份。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from database.connection import get_connection  # noqa: E402

STREAM_TPL = "https://music.163.com/song/media/outer/url?id={}.mp3"
SLEEP = 0.4


def playable(session: requests.Session, url: str) -> bool:
    """302 落到真文件才算可播 —— VIP/版权受限的歌会 302 到 /404。"""
    try:
        resp = session.get(url, timeout=12, allow_redirects=True, stream=True)
        ok = (resp.status_code == 200
              and "404" not in resp.url
              and "audio" in (resp.headers.get("content-type") or ""))
        resp.close()
        return ok
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    cookie = os.getenv("NETEASE_COOKIE", "").strip()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    if cookie:
        session.headers["Cookie"] = cookie
        print("已带上 NETEASE_COOKIE（VIP 歌这次也有机会）")
    else:
        print("匿名模式（VIP/版权受限的歌会被 404 —— 要覆盖请看脚本头部说明）")

    connection = get_connection()
    with connection.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT u.external_id, u.title, u.matched_track_id
            FROM user_playlist_track u
            LEFT JOIN track_audio_feature f
                   ON f.track_id = u.matched_track_id AND f.preview_url IS NOT NULL
            WHERE u.provider = 'netease' AND u.match_status = 'MATCHED'
              AND u.matched_track_id IS NOT NULL AND f.track_id IS NULL
              AND u.user_removed = 0
            """)
        targets = cur.fetchall()
    if args.limit:
        targets = targets[: args.limit]
    print(f"目标：{len(targets)} 首已对齐但没有试听的网易云歌")

    ok = miss = 0
    for i, t in enumerate(targets, 1):
        url = STREAM_TPL.format(t["external_id"])
        if not playable(session, url):
            miss += 1
            print(f"  [{i}/{len(targets)}] {t['title'][:22]} —— 外链拿不到（VIP/版权）")
            time.sleep(SLEEP)
            continue
        with connection.cursor() as cur:
            cur.execute("""
                INSERT INTO track_audio_feature
                    (track_id, arousal_measured, preview_url,
                     artist_verified, analyzer_version)
                VALUES (%s, NULL, %s, 0, 'netease-fallback')
                """, (t["matched_track_id"], url))
        connection.commit()
        ok += 1
        print(f"  [{i}/{len(targets)}] {t['title'][:22]} ✓")
        time.sleep(SLEEP)

    connection.close()
    print(f"\n补回 {ok} 首，拿不到 {miss} 首（{ok}/{len(targets)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
