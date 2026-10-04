"""按 Release MBID 入库 —— Java 后端按需入库（③）调的就是这个脚本。

用法：
    python ingest_release.py <release-mbid>

退出码（Java 判成败的唯一依据）：
    0 = 入库成功
    1 = 入库失败（网络 / 数据异常 / 没有 release-group）
    2 = 参数不对

输出约定：
    成功  stdout 一行 `INGEST_OK <mbid> tracks=.. albums=.. api=.. elapsed=..`
    失败  stderr 一行 `INGEST_FAIL <mbid> <原因>`

【为什么自己把 stdout 改成 UTF-8】
Windows 下输出重定向时 Python 默认用 GBK，编不出 ✓ 和中文错误信息，
print 会直接抛异常 —— 那样 exit code 和日志全都不可信。
Java 那边要读这个输出，在这儿兜住比要求调用方设环境变量可靠。
⚠ 读日志的一方（Java）必须按 UTF-8 解码。
"""

from __future__ import annotations

import sys

# 必须放在任何 print 之前
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from config.settings import MUSICBRAINZ_CONFIG  # noqa: E402
from cover import CoverArtClient, ensure_cover  # noqa: E402
from database.connection import get_connection  # noqa: E402
from musicbrainz import MusicBrainzClient  # noqa: E402
from musicbrainz.adapter import MusicBrainzDataAdapter  # noqa: E402
from musicbrainz.ingest import (  # noqa: E402
    build_release_ingest_context,
    ingest_release,
)

# 从 main.py 借 ImportStats：统计口径和整艺人导入共用一套，不另立一份
# （另立一份的话，两边迟早对不上，而且对不上时没人会发现）
from main import ImportStats  # noqa: E402


def fetch_cover_for_release(connection, release_mbid: str) -> str:
    """刚入库的 release 对应的专辑，顺手把封面抓下来。返回一句状态描述。

    【为什么要单独一个客户端、还调小重试】这条路径是用户点了「入库」在等的，
    而 cover.store.ensure_cover 不会抛异常 —— 所以卡住的时间就是用户多等的时间。
    默认的 3 次 × 20 秒最坏会给一次 6 秒的入库加上 60 秒。
    调到 2 × 15 秒，最坏 30 秒，仍然远低于 Java 那边 300 秒的任务超时。
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT album_id FROM music_release WHERE musicbrainz_id = %s",
            (release_mbid,),
        )
        row = cursor.fetchone()

    if row is None:
        # 理论上不会：上面刚把这个 release 写进去并 commit 了
        return "没找到刚入库的 release"

    client = CoverArtClient(
        user_agent=MUSICBRAINZ_CONFIG["user_agent"],
        timeout=15,
        max_retries=2,
    )
    return ensure_cover(client, int(row["album_id"]), [release_mbid])


def run(release_mbid: str) -> int:

    stats = ImportStats()

    client = MusicBrainzClient(
        user_agent=MUSICBRAINZ_CONFIG["user_agent"]
    )

    adapter = MusicBrainzDataAdapter()

    connection = get_connection()

    ctx = build_release_ingest_context(connection)

    cover_note = ""

    try:

        if not ingest_release(
            connection,
            client,
            adapter,
            ctx,
            release_mbid,
            stats,
        ):
            # 缺 release-group。不是异常，但也没东西可入库
            connection.rollback()

            print(
                f"INGEST_FAIL {release_mbid} "
                f"这个 release 没有 release-group",
                file=sys.stderr,
            )

            return 1

        connection.commit()

        # 【入库后顺手补一张封面】③ 按需入库进来的专辑原来没人抓封面 ——
        # CoverImage 直接拼 /covers/{albumId}.jpg，文件不在就是一片占位块。
        #
        # 放在 commit 之后有两个理由：一次网络调用不该包在事务里；
        # 而且封面抓不到也绝不能让这次入库算失败（ensure_cover 不抛异常）
        cover_note = fetch_cover_for_release(connection, release_mbid)

    except Exception as e:

        connection.rollback()

        print(
            f"INGEST_FAIL {release_mbid} "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
        )

        return 1

    finally:
        connection.close()

    # 封面那句走 stderr：stdout 的 INGEST_OK 是「一行结果」，调用方在读它。
    # 多塞一个字段就多一处可能被解析坏的地方。stderr 被 Java 合进日志，
    # 排障时看得到，不影响协议
    print(f"COVER {release_mbid} {cover_note}", file=sys.stderr)

    print(
        f"INGEST_OK {release_mbid} "
        f"tracks={stats.track_count} "
        f"albums={stats.album_count} "
        f"api={stats.api_request_count} "
        f"elapsed={stats.elapsed():.2f}s"
    )

    return 0


def main() -> int:

    if len(sys.argv) != 2 or not sys.argv[1].strip():

        print(
            "用法：python ingest_release.py <release-mbid>",
            file=sys.stderr,
        )

        return 2

    return run(sys.argv[1].strip())


if __name__ == "__main__":
    sys.exit(main())
