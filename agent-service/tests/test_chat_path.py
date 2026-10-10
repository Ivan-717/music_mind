"""探索路径的解析契约（`chat._resolve_path`）。

**为什么这组测试存在**：前端 ExploreView 的路径模板依赖这里产出的字段名。
后端改字段名而前端不知道时，表现是「整条路径静默消失」—— 和这次要修的
那个病（parse 不取 path，M6 功能死了半年）是同一族。把契约钉死。

全部离线：connection 是假的（`_in_library` 只用到 cursor().execute().fetchone()）。
"""

from __future__ import annotations

from musicmind_agent.chat import MAX_PATH_STEPS, _resolve_path


class FakeCursor:
    def __init__(self, hit_names: set[str]):
        self.hit_names = hit_names
        self._hit = False

    def execute(self, sql, args):
        # _in_library 的 SQL：REPLACE(name,' ','') = REPLACE(%s,' ','')
        self._hit = args[0] in self.hit_names

    def fetchone(self):
        return (1,) if self._hit else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    """只认「库里有哪些名字」的最小连接。"""

    def __init__(self, in_library: set[str] | None = None):
        self._names = set(in_library or ())

    def cursor(self):
        return FakeCursor(self._names)


def _raw(steps: list[dict]) -> dict:
    return {"topic": "Britpop", "steps": steps}


def test_step_fields_are_the_frontend_contract():
    """steps 的字段名就是前端模板取的那些（.order/.name/.owned/.grab/.relation/.why）。

    改这里 = 必须同时改前端，且前端模板用的是 `s.in_library`、`s.release_mbid` 等 ——
    少一个键模板就是静默不渲染。
    """
    raw = _raw([
        {"name": "Oasis", "kind": "artist", "why_here": "起点", "relation": None},
        {"name": "Blur", "kind": "artist", "why_here": "对位",
         "relation": "和 Oasis 打过英伦之战"},
    ])
    out = _resolve_path(raw, {"Oasis", "Blur"}, [], [], FakeConnection(), {})

    assert out["topic"] == "Britpop"
    assert [s["name"] for s in out["steps"]] == ["Oasis", "Blur"]
    for s in out["steps"]:
        assert set(s) == {
            "order", "name", "kind", "release_mbid", "release_title",
            "release_artist", "in_library", "why_here", "relation",
        }


def test_one_station_is_not_a_path():
    """一站的「路径」没有意义 —— 返回 None，前端 v-if 就不渲染。"""
    out = _resolve_path(_raw([{"name": "Oasis"}]), {"Oasis"}, [], [], FakeConnection(), {})
    assert out is None


def test_stations_without_a_source_are_dropped():
    """模型会顺手写它没查过的名字（Pulp / Suede）—— 没出处的直接丢。"""
    # 只有 Oasis 有出处 → 只剩一站 → None
    out = _resolve_path(_raw([{"name": "Oasis"}, {"name": "Pulp"}]),
                        {"Oasis"}, [], [], FakeConnection(), {})
    assert out is None

    # 两站有出处、一站没有 → 留下两站，且 order 重排不留空号
    out2 = _resolve_path(
        _raw([{"name": "Oasis"}, {"name": "Blur"}, {"name": "Pulp"}]),
        {"Oasis", "Blur"}, [], [], FakeConnection(), {})
    assert [s["name"] for s in out2["steps"]] == ["Oasis", "Blur"]
    assert [s["order"] for s in out2["steps"]] == [1, 2]


def test_name_in_knowledge_text_counts_as_source():
    """正文里出现过的名字也算出处 —— 这是最常走的一条路（模型查「Britpop」
    那一页，正文提到 Oasis/Suede，那些名字是真实出现过的）。"""
    out = _resolve_path(
        _raw([{"name": "Oasis"}, {"name": "Suede"}]),
        set(), ["……Oasis 与 Suede 都属于 Britpop 浪潮……"],
        [], FakeConnection(), {})
    assert out is not None
    assert len(out["steps"]) == 2


def test_mbid_only_from_upstream():
    """模型会照着 uuid 的格式编一个 mbid，而抓取会照它去抓（404 或抓错专辑）。
    只认上游真返回过的那张，标题/艺人也取上游的、不取模型写的。"""
    upstream = [{"release_mbid": "real-uuid-1",
                 "title": "Definitely Maybe", "artist": "Oasis"}]
    raw = _raw([
        {"name": "Oasis", "release_mbid": "real-uuid-1"},
        {"name": "Blur", "release_mbid": "made-up-uuid"},
    ])
    out = _resolve_path(raw, {"Oasis", "Blur"}, [], upstream, FakeConnection(), {})
    s1, s2 = out["steps"]
    assert s1["release_mbid"] == "real-uuid-1"
    assert s1["release_title"] == "Definitely Maybe"
    assert s1["release_artist"] == "Oasis"
    assert s2["release_mbid"] is None
    assert s2["release_title"] is None


def test_in_library_is_queried_not_model_written():
    """「已有」由代码查（模型不知道库里有什么）——fake 库里只有 Oasis。"""
    raw = _raw([{"name": "Oasis"}, {"name": "Blur"}])
    out = _resolve_path(raw, {"Oasis", "Blur"}, [], [],
                        FakeConnection(in_library={"Oasis"}), {})
    assert out["steps"][0]["in_library"] is True
    assert out["steps"][1]["in_library"] is False


def test_capped_at_max_steps():
    steps = [{"name": f"名字{i}"} for i in range(MAX_PATH_STEPS + 4)]
    out = _resolve_path(_raw(steps), {s["name"] for s in steps}, [], [],
                        FakeConnection(), {})
    assert len(out["steps"]) == MAX_PATH_STEPS


def test_garbage_shapes_return_none():
    """None / 非 dict / steps 不是列表 —— 都不能炸，统一 None。"""
    assert _resolve_path(None, set(), [], [], FakeConnection(), {}) is None
    assert _resolve_path("不是字典", set(), [], [], FakeConnection(), {}) is None
    assert _resolve_path({"topic": "x", "steps": []}, set(), [], [],
                         FakeConnection(), {}) is None
