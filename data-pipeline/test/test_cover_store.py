"""按需封面（cover/store.py）的测试。全部离线 —— 客户端用假的，不碰网络。

【为什么值得单独测】这条路径挂在「按需入库」上：用户点一下「入库」，
它就应该顺手把封面抓到本地。而它一旦出错是**静默**的 ——
CoverImage 拼不到文件就退成占位块，看起来只是「没封面」，
不像故障，能一直躺着没人发现。所以用测试把返回的三种状态钉死。
"""

from __future__ import annotations

import pytest

from cover import store


class FakeClient:
    """假的 Cover Art 客户端。by_mbid 里放 bytes / None（404）/ Exception。"""

    def __init__(self, by_mbid: dict):
        self.by_mbid = by_mbid

    def fetch_front(self, mbid: str, size: int = 250):
        value = self.by_mbid.get(mbid)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture(autouse=True)
def _tmp_cover_dir(tmp_path, monkeypatch):
    """绝不许往真的 frontend/public/covers 里写 —— 那是一个进 git 里的目录，
    测试跑一遍就往里塞图，迟早有人把它提交上去。"""
    monkeypatch.setattr(store, "COVER_DIR", tmp_path)
    return tmp_path


def test_writes_the_file():
    client = FakeClient({"m1": b"x" * 100})
    note = store.ensure_cover(client, 7, ["m1"])

    assert "已抓取" in note
    assert store.cover_path(7).read_bytes() == b"x" * 100


def test_skips_when_file_already_there():
    store.cover_path(7).parent.mkdir(parents=True, exist_ok=True)
    store.cover_path(7).write_bytes(b"old")

    client = FakeClient({"m1": b"new"})
    note = store.ensure_cover(client, 7, ["m1"])

    assert note == "已有封面，跳过"
    assert store.cover_path(7).read_bytes() == b"old", "不该覆盖已有的图"


def test_falls_back_to_the_next_release():
    """同一个专辑不同发行的封面是各自独立的 —— 一个没有就用下一个。"""
    client = FakeClient({"m1": None, "m2": b"y" * 50})
    note = store.ensure_cover(client, 7, ["m1", "m2"])

    assert "已抓取" in note
    assert store.cover_path(7).exists()


def test_client_error_does_not_raise():
    """网络出错绝不能抛 —— 它会顺着 ingest_release 冒到最外层，
    把一次成功的入库判成失败，而用户那一行会永远留着「未收录」。
    那个代价比「没封面」大得多。"""
    client = FakeClient({"m1": RuntimeError("proxy 连不上")})
    note = store.ensure_cover(client, 7, ["m1"])

    assert "全都没抓到" in note
    assert "proxy 连不上" in note
    assert not store.cover_path(7).exists()


def test_one_bad_release_does_not_stop_the_others():
    client = FakeClient({"m1": RuntimeError("超时"), "m2": b"z" * 10})
    note = store.ensure_cover(client, 7, ["m1", "m2"])

    assert "已抓取" in note


def test_reports_when_there_is_genuinely_no_cover():
    """404 是正常情况，不是错误 —— 措辞上要和「抓取出错」分开，
    否则排障时看不出该去修代码还是该接受现实。"""
    client = FakeClient({"m1": None, "m2": None})
    note = store.ensure_cover(client, 7, ["m1", "m2"])

    assert note == "所有 release 都没有封面"
    assert "出错" not in note


def test_no_releases_is_a_noop():
    assert "跳过" in store.ensure_cover(FakeClient({}), 7, [])
    assert "跳过" in store.ensure_cover(FakeClient({}), 0, ["m1"])
