import json
from pathlib import Path

from musicbrainz.adapter import (
    MusicBrainzDataAdapter,
    normalize_date,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_normalize_date():
    assert normalize_date(None) is None
    assert normalize_date("") is None

    assert normalize_date("1988") == "1988-01-01"
    assert normalize_date("1988-11") == "1988-11-01"
    assert normalize_date("1988-11-15") == "1988-11-15"

    assert normalize_date("1988-13-01") is None
    assert normalize_date("不是日期") is None


def test_artist_to_musicmind():
    data = load_fixture("artist.json")

    adapter = MusicBrainzDataAdapter()
    result = adapter.artist_to_musicmind(data)

    assert result["musicbrainz_id"] == data["id"]
    assert result["name"] == data["name"]
    assert result["sort_name"] == data["sort-name"]
    assert result["disambiguation"] == data.get("disambiguation")


def test_artist_aliases_to_musicmind():
    data = load_fixture("artist.json")

    adapter = MusicBrainzDataAdapter()
    result = adapter.artist_aliases_to_musicmind(data)

    assert len(result) == 14

    # 每条 alias 至少应该保留 name
    for alias in result:
        assert alias["name"]

    # 找一条原始数据中没有 locale 的 alias，
    # 验证 adapter 是否把 None 转成了空字符串。
    raw_alias_without_locale = next(
        (
            alias
            for alias in data.get("aliases", [])
            if not alias.get("locale")
        ),
        None,
    )

    if raw_alias_without_locale is not None:
        converted = next(
            item
            for item in result
            if item["name"] == raw_alias_without_locale["name"]
        )

        assert converted["locale"] == ""


def test_artist_aliases_null_primary_becomes_false():
    """
    MusicBrainz 会把 primary / locale 显式返回 null。

    .get("primary", False) 挡不住这种情况——
    只在 key 缺失时用 default，key 存在但值为 null 时返回 None，
    会导致 artist_alias.is_primary (NOT NULL) 插入失败。

    实测：Various Artists 的 224 个别名里有 103 个 primary 为 null。
    """

    adapter = MusicBrainzDataAdapter()

    data = {
        "aliases": [
            {"name": "有值", "locale": "en", "primary": True},
            {"name": "显式 null", "locale": None, "primary": None},
            {"name": "字段缺失"},
        ]
    }

    result = adapter.artist_aliases_to_musicmind(data)

    assert result[0]["is_primary"] is True
    assert result[1]["is_primary"] is False
    assert result[2]["is_primary"] is False

    # locale 同理，NOT NULL DEFAULT ''
    assert result[1]["locale"] == ""
    assert result[2]["locale"] == ""


def test_album_to_musicmind():
    data = load_fixture("release.json")
    release_group = data["release-group"]

    adapter = MusicBrainzDataAdapter()
    result = adapter.album_to_musicmind(release_group)

    assert result["musicbrainz_id"] == release_group["id"]
    assert result["name"] == release_group["title"]
    assert result["release_date"] == "2001-09-20"
    assert result["primary_type"] == release_group.get("primary-type")
    assert result["secondary_types"] == release_group.get(
        "secondary-types",
        [],
    )


def test_album_artists_to_musicmind():
    data = load_fixture("release.json")
    release_group = data["release-group"]

    adapter = MusicBrainzDataAdapter()
    result = adapter.album_artists_to_musicmind(release_group)

    artist_credits = release_group.get("artist-credit", [])

    expected = [
        credit
        for credit in artist_credits
        if credit.get("artist", {}).get("id")
    ]

    assert len(result) == len(expected)

    for item in result:
        assert item["artist_musicbrainz_id"]
        assert "credited_name" in item
        assert "join_phrase" in item


def test_track_artists_to_musicmind():
    data = load_fixture("release.json")

    adapter = MusicBrainzDataAdapter()

    track = data["media"][0]["tracks"][0]
    recording = track["recording"]

    result = adapter.track_artists_to_musicmind(recording)

    artist_credits = recording.get("artist-credit", [])

    expected = [
        credit
        for credit in artist_credits
        if credit.get("artist", {}).get("id")
    ]

    assert len(result) == len(expected)

    for item in result:
        assert item["artist_musicbrainz_id"]
        assert "credited_name" in item
        assert "join_phrase" in item


def test_artist_credit_without_artist_is_skipped():
    adapter = MusicBrainzDataAdapter()

    data = {
        "artist-credit": [
            {
                "joinphrase": " & ",
            },
            {
                "artist": {
                    "id": "artist-1",
                    "name": "测试歌手",
                },
                "joinphrase": "",
            },
        ]
    }

    result = adapter.album_artists_to_musicmind(data)

    assert len(result) == 1
    assert result[0]["artist_musicbrainz_id"] == "artist-1"


def test_track_artist_credit_without_artist_is_skipped():
    adapter = MusicBrainzDataAdapter()

    data = {
        "artist-credit": [
            {
                "joinphrase": " feat. ",
            },
            {
                "artist": {
                    "id": "artist-2",
                    "name": "测试歌手2",
                },
                "joinphrase": "",
            },
        ]
    }

    result = adapter.track_artists_to_musicmind(data)

    assert len(result) == 1
    assert result[0]["artist_musicbrainz_id"] == "artist-2"


def test_release_to_musicmind():
    data = load_fixture("release.json")

    adapter = MusicBrainzDataAdapter()
    result = adapter.release_to_musicmind(data)

    assert result["musicbrainz_id"] == data["id"]
    assert result["album_musicbrainz_id"] == data["release-group"]["id"]

    # 这里明确验证：
    # adapter 阶段仍然保存外部 MBID，
    # 到 main.py 才会通过 album_ids 转成本地 album_id。
    assert isinstance(result["album_musicbrainz_id"], str)

    assert result["title"] == data["title"]
    assert result["release_date"] == "2001-09-20"
    assert result["country"] == data.get("country")
    assert result["status"] == data.get("status")


def test_release_tracks_to_musicmind():
    data = load_fixture("release.json")

    adapter = MusicBrainzDataAdapter()
    result = adapter.release_tracks_to_musicmind(data)

    assert len(result) == 10

    for item in result:
        assert item["release_musicbrainz_id"] == data["id"]
        assert item["track_musicbrainz_recording_id"]
        assert item["track_number"] is not None
        assert item["disc_number"] is not None


def test_track_to_musicmind():
    data = load_fixture("release.json")

    adapter = MusicBrainzDataAdapter()

    track = data["media"][0]["tracks"][0]
    result = adapter.track_to_musicmind(track)

    recording = track["recording"]

    assert result["musicbrainz_recording_id"] == recording["id"]
    assert result["name"] == recording["title"]
    assert result["duration_ms"] == recording["length"]

def test_genres_to_musicmind():
    adapter = MusicBrainzDataAdapter()

    data = {
        "genres": [
            {
                "id": "xxx",
                "name": "mandopop",
                "count": 4,
            },
            {
                "id": "yyy",
                "name": "pop",
                "count": 2,
            },
        ]
    }

    result = adapter.genres_to_musicmind(data)

    assert result == [
        {"name": "mandopop", "weight": 4},
        {"name": "pop", "weight": 2},
    ]

    # 归一化：字段缺失 / 显式 null 都返回空列表
    assert adapter.genres_to_musicmind({}) == []
    assert adapter.genres_to_musicmind({"genres": None}) == []