"""按 release 入库的测试。

默认不碰网络：把 client.get_release 换成一个返回 fixtures/release.json 的假客户端。
真实 API 的那条用 -m slow 单独跑：

    .venv/Scripts/python.exe -m pytest test/test_ingest_release.py -m slow
"""

import copy
import json
import re
import uuid
from pathlib import Path

import pytest

from main import ImportStats
from musicbrainz import MusicBrainzClient
from musicbrainz.adapter import MusicBrainzDataAdapter
from musicbrainz.ingest import (
    build_release_ingest_context,
    ingest_release,
)

FIXTURE = Path(__file__).parent / "fixtures" / "release.json"

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# 测试专用命名空间。换掉它 = 换一批测试 MBID，仅此而已
TEST_NS = uuid.UUID("6f1d0e2a-0000-4000-8000-000000000000")


def rewrite_mbids(obj):
    """把 fixture 里所有 MBID 换成本次测试专用的。

    范特西早就被整艺人导入进库了。直接拿原 MBID 测，所有 upsert 都会命中已有行，
    永远走不到「冷插入」—— 而按需入库（③）的典型场景恰恰是插入本地还没有的专辑。

    用 uuid5 派生而不是随机数：同一份 fixture 每次派生出同一批 MBID，
    两次入库才能对上同一批行；MBID 之间的对应关系（哪个 artist 属于哪张专辑）也保持不变。
    """
    if isinstance(obj, dict):
        return {k: rewrite_mbids(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rewrite_mbids(v) for v in obj]
    if isinstance(obj, str) and UUID_RE.match(obj):
        return str(uuid.uuid5(TEST_NS, obj))
    return obj

# release 落库会碰到的表。任何一个翻倍都说明 upsert 写成了 insert
TABLES = [
    "artist",
    "album",
    "album_artist",
    "album_genre",
    "music_release",
    "track",
    "track_artist",
    "release_track",
]


class FakeClient:
    """只实现 ingest_release 用到的那一个方法。"""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def get_release(self, release_mbid: str) -> dict:
        self.calls += 1
        # 每次都给一份新的：真实场景里每次调用都是一个独立的 HTTP 响应，
        # 而且 adapter 有可能就地改传入的 dict，共用一份会让第二遍结果失真
        return copy.deepcopy(self.payload)


def count_rows(db, table_name: str) -> int:
    with db.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) AS n FROM `{table_name}`")
        return cursor.fetchone()["n"]


def snapshot(db) -> dict:
    return {name: count_rows(db, name) for name in TABLES}


def test_ingest_release_writes_and_is_idempotent(db):
    payload = rewrite_mbids(
        json.loads(FIXTURE.read_text(encoding="utf-8"))
    )

    client = FakeClient(payload)
    adapter = MusicBrainzDataAdapter()

    before = snapshot(db)

    # ---- 第 1 遍 ----
    first = ImportStats()

    assert ingest_release(
        db,
        client,
        adapter,
        build_release_ingest_context(db),
        payload["id"],
        first,
    ) is True

    after_first = snapshot(db)

    assert after_first["track"] == before["track"] + 10
    assert after_first["music_release"] == before["music_release"] + 1
    assert after_first["album"] == before["album"] + 1
    assert first.skipped_release_count == 0

    # ---- 第 2 遍：全新的 ctx ----
    # 缓存是「一次导入生命周期」内的东西。第二次入库是 Java 起的新进程，
    # 拿到的是空缓存 —— 这里必须用新 ctx 才能测到真实的第二次行为
    # （复用旧 ctx 的话缓存全命中，根本走不到 upsert）
    second = ImportStats()

    assert ingest_release(
        db,
        client,
        adapter,
        build_release_ingest_context(db),
        payload["id"],
        second,
    ) is True

    after_second = snapshot(db)

    # 【断言的是行数，不是 stats】
    # stats 里的 album_count / track_count 统计的是「缓存未命中次数」，
    # 第二遍缓存同样是空的，所以它们照样是 10 和 1 —— 拿 stats 判断幂等会得出错误结论
    assert after_second == after_first

    # 两次都真的请求了上游（幂等靠 upsert，不是靠跳过）
    assert client.calls == 2


def test_ingest_release_without_release_group_writes_nothing(db):
    """没有 release-group 时返回 False、记一次 skip，且一个字节都不写。"""

    payload = rewrite_mbids(
        json.loads(FIXTURE.read_text(encoding="utf-8"))
    )
    payload.pop("release-group")

    client = FakeClient(payload)
    adapter = MusicBrainzDataAdapter()

    before = snapshot(db)
    stats = ImportStats()

    assert ingest_release(
        db,
        client,
        adapter,
        build_release_ingest_context(db),
        payload["id"],
        stats,
    ) is False

    assert stats.skipped_release_count == 1
    assert snapshot(db) == before


def test_stale_cache_after_rollback_breaks_next_release(db):
    """【回归】回滚之后不调 forget_uncommitted，同一个艺人后面的 release 会全线撞外键。

    这里刻意【复用同一个 ctx 跑两次】—— 那正是 main.py 导入循环的真实形态：
    ctx 活在整个导入期间，一个 release 失败回滚后接着跑下一个。

    打桩让第一次在「release 写入」这一步炸掉：此时 album 的 id 已经进了缓存，
    而事务被回滚。回滚只回滚数据库、回滚不了内存，且 MySQL 的自增值不后退 ——
    缓存里留下的是一个永远不会有行占用的死 id。

    第二次跑同一个 release-group（payload 完全正常）：缓存命中，连 album 都不再
    upsert，直接把死 id 写进 music_release.album_id → 撞 fk_music_release_album。
    这就是「一次失败之后同一艺人全线崩」的成因。
    """
    good = rewrite_mbids(json.loads(FIXTURE.read_text(encoding="utf-8")))
    adapter = MusicBrainzDataAdapter()

    ctx = build_release_ingest_context(db)
    real_upsert = ctx.release_repository.upsert

    def boom(*args, **kwargs):
        raise RuntimeError("模拟写库中途失败")

    # ---- 第一次：写到 release 时炸掉 ----
    ctx.release_repository.upsert = boom
    with pytest.raises(RuntimeError):
        ingest_release(db, FakeClient(good), adapter, ctx, good["id"], ImportStats())
    ctx.release_repository.upsert = real_upsert

    assert ctx.album_ids, "album id 应该在失败前进过缓存，否则这个测试没测到东西"

    db.rollback()

    # ---- 不调 forget_uncommitted：复用死 id，撞外键 ----
    with pytest.raises(Exception) as dirty:
        ingest_release(db, FakeClient(good), adapter, ctx, good["id"], ImportStats())
    assert "foreign key" in str(dirty.value).lower(), str(dirty.value)

    db.rollback()

    # ---- 调了就没事：同一个 payload 顺利完成 ----
    ctx.forget_uncommitted()

    before = snapshot(db)
    assert ingest_release(db, FakeClient(good), adapter, ctx, good["id"], ImportStats()) is True
    after = snapshot(db)

    assert after["track"] == before["track"] + 10
    assert after["music_release"] == before["music_release"] + 1


@pytest.mark.slow
def test_ingest_release_real_api(db):
    """真实 API 取一次，换成测试 MBID 后走两遍入库。

    取真实数据是为了验证线上返回的结构 ingest 吃得下（fixture 是静态的，
    上游改字段它不会知道）；换 MBID 是为了让写入落在测试命名空间里，
    断言才能和库里已有的真实数据无关。
    """
    from config.settings import MUSICBRAINZ_CONFIG

    live = MusicBrainzClient(
        user_agent=MUSICBRAINZ_CONFIG["user_agent"]
    ).get_release(
        "0377c05a-0da4-46f7-a153-52e80e7adac1"  # 范特西
    )

    payload = rewrite_mbids(live)

    client = FakeClient(payload)
    adapter = MusicBrainzDataAdapter()

    before = snapshot(db)
    first = ImportStats()

    assert ingest_release(
        db,
        client,
        adapter,
        build_release_ingest_context(db),
        payload["id"],
        first,
    ) is True

    after_first = snapshot(db)

    assert after_first["track"] == before["track"] + 10
    assert after_first["music_release"] == before["music_release"] + 1

    second = ImportStats()

    assert ingest_release(
        db,
        client,
        adapter,
        build_release_ingest_context(db),
        payload["id"],
        second,
    ) is True

    assert snapshot(db) == after_first
