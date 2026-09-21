from musicbrainz.repository import (
    ArtistRepository,
    ArtistAliasRepository,
    AlbumRepository,
    AlbumArtistRepository,
    ReleaseRepository,
    TrackRepository,
    TrackArtistRepository,
    ReleaseTrackRepository,
)


def count_rows(db, table_name: str) -> int:
    with db.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) AS n FROM `{table_name}`")
        return cursor.fetchone()["n"]


def test_artist_repository_upsert(db):
    repository = ArtistRepository(db)

    mbid = "00000000-0000-0000-0000-000000000001"

    before = count_rows(db, "artist")

    artist1 = {
        "musicbrainz_id": mbid,
        "name": "测试歌手",
        "sort_name": "Test Artist",
        "disambiguation": None,
    }

    artist2 = {
        "musicbrainz_id": mbid,
        "name": "测试歌手（更新）",
        "sort_name": "Test Artist Updated",
        "disambiguation": "test",
    }

    artist_id_1 = repository.upsert(
        artist1,
        autocommit=False,
    )

    artist_id_2 = repository.upsert(
        artist2,
        autocommit=False,
    )

    after = count_rows(db, "artist")

    assert after == before + 1
    assert artist_id_1 == artist_id_2

    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT name, sort_name, disambiguation
            FROM artist
            WHERE id = %s
            """,
            (artist_id_1,),
        )
        row = cursor.fetchone()

    assert row["name"] == "测试歌手（更新）"
    assert row["sort_name"] == "Test Artist Updated"
    assert row["disambiguation"] == "test"


def test_artist_repository_ensure_stub(db):
    repository = ArtistRepository(db)

    mbid = "00000000-0000-0000-0000-000000000002"

    artist_id = repository.upsert(
        {
            "musicbrainz_id": mbid,
            "name": "完整歌手",
            "sort_name": "Complete Artist",
            "disambiguation": "full",
        },
        autocommit=False,
    )

    stub_id = repository.ensure_stub(
        mbid,
        "错误的 Stub 名称",
        autocommit=False,
    )

    assert stub_id == artist_id

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT name FROM artist WHERE id = %s",
            (artist_id,),
        )
        row = cursor.fetchone()

    # ensure_stub 绝对不能覆盖已有完整数据
    assert row["name"] == "完整歌手"


def test_artist_repository_ensure_stub_name_none(db):
    repository = ArtistRepository(db)

    mbid = "00000000-0000-0000-0000-000000000003"

    artist_id = repository.ensure_stub(
        mbid,
        None,
        autocommit=False,
    )

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT name FROM artist WHERE id = %s",
            (artist_id,),
        )
        row = cursor.fetchone()

    assert row["name"] == mbid


def test_artist_alias_repository(db):
    artist_repository = ArtistRepository(db)
    alias_repository = ArtistAliasRepository(db)

    artist_id = artist_repository.ensure_stub(
        "00000000-0000-0000-000000000004",
        "测试歌手",
        autocommit=False,
    )

    alias = {
        "name": "测试歌手别名",
        "locale": "zh_Hans",
        "is_primary": False,
    }

    before = count_rows(db, "artist_alias")

    alias_repository.upsert(
        artist_id,
        alias,
        autocommit=False,
    )

    alias_updated = {
        "name": "测试歌手别名",
        "locale": "zh_Hans",
        "is_primary": True,
    }

    alias_repository.upsert(
        artist_id,
        alias_updated,
        autocommit=False,
    )

    after = count_rows(db, "artist_alias")

    assert after == before + 1

    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT is_primary
            FROM artist_alias
            WHERE artist_id = %s
              AND name = %s
              AND locale = %s
            """,
            (
                artist_id,
                "测试歌手别名",
                "zh_Hans",
            ),
        )
        row = cursor.fetchone()

    assert row["is_primary"] in (1, True)


def test_album_repository(db):
    artist_repository = ArtistRepository(db)
    album_repository = AlbumRepository(db)

    mbid = "00000000-0000-0000-0000-000000000010"

    before = count_rows(db, "album")

    album1 = {
        "musicbrainz_id": mbid,
        "name": "测试专辑",
        "release_date": "2001-09-20",
        "primary_type": "Album",
        "secondary_types": [],
    }

    album2 = {
        "musicbrainz_id": mbid,
        "name": "测试专辑（更新）",
        "release_date": "2001-09-21",
        "primary_type": "Album",
        "secondary_types": ["Compilation"],
    }

    album_id_1 = album_repository.upsert(
        album1,
        autocommit=False,
    )

    album_id_2 = album_repository.upsert(
        album2,
        autocommit=False,
    )

    after = count_rows(db, "album")

    assert after == before + 1
    assert album_id_1 == album_id_2

    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT name, release_date, secondary_types
            FROM album
            WHERE id = %s
            """,
            (album_id_1,),
        )
        row = cursor.fetchone()

    assert row["name"] == "测试专辑（更新）"
    assert str(row["release_date"]) == "2001-09-21"


def test_album_artist_repository(db):
    artist_repository = ArtistRepository(db)
    album_repository = AlbumRepository(db)
    relation_repository = AlbumArtistRepository(db)

    artist_id = artist_repository.ensure_stub(
        "00000000-0000-0000-0000-000000000011",
        "测试歌手",
        autocommit=False,
    )

    album_id = album_repository.upsert(
        {
            "musicbrainz_id": "00000000-0000-0000-0000-000000000012",
            "name": "测试专辑",
            "release_date": "2001-01-01",
            "primary_type": "Album",
            "secondary_types": [],
        },
        autocommit=False,
    )

    before = count_rows(db, "album_artist")

    relation_repository.upsert(
        album_id,
        artist_id,
        "测试歌手",
        "",
        autocommit=False,
    )

    relation_repository.upsert(
        album_id,
        artist_id,
        "测试歌手（更新）",
        " & ",
        autocommit=False,
    )

    after = count_rows(db, "album_artist")

    assert after == before + 1

    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT credited_name, join_phrase
            FROM album_artist
            WHERE album_id = %s
              AND artist_id = %s
            """,
            (album_id, artist_id),
        )
        row = cursor.fetchone()

    assert row["credited_name"] == "测试歌手（更新）"
    assert row["join_phrase"] == " & "


def test_release_repository(db):
    album_repository = AlbumRepository(db)
    release_repository = ReleaseRepository(db)

    album_id_1 = album_repository.upsert(
        {
            "musicbrainz_id": "00000000-0000-0000-0000-000000000020",
            "name": "专辑 A",
            "release_date": "2001-01-01",
            "primary_type": "Album",
            "secondary_types": [],
        },
        autocommit=False,
    )

    album_id_2 = album_repository.upsert(
        {
            "musicbrainz_id": "00000000-0000-0000-0000-000000000021",
            "name": "专辑 B",
            "release_date": "2002-01-01",
            "primary_type": "Album",
            "secondary_types": [],
        },
        autocommit=False,
    )

    release_mbid = "00000000-0000-0000-0000-000000000022"

    before = count_rows(db, "music_release")

    release1 = {
        "musicbrainz_id": release_mbid,
        "album_id": album_id_1,
        "title": "测试发行",
        "release_date": "2001-01-01",
        "country": "TW",
        "status": "Official",
    }

    release2 = {
        "musicbrainz_id": release_mbid,
        "album_id": album_id_2,
        "title": "测试发行（更新）",
        "release_date": "2002-01-01",
        "country": "CN",
        "status": "Official",
    }

    release_id_1 = release_repository.upsert(
        release1,
        autocommit=False,
    )

    release_id_2 = release_repository.upsert(
        release2,
        autocommit=False,
    )

    after = count_rows(db, "music_release")

    assert after == before + 1
    assert release_id_1 == release_id_2

    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT album_id, title
            FROM music_release
            WHERE id = %s
            """,
            (release_id_1,),
        )
        row = cursor.fetchone()

    assert row["album_id"] == album_id_2
    assert row["title"] == "测试发行（更新）"


def test_track_repository(db):
    track_repository = TrackRepository(db)

    mbid = "00000000-0000-0000-0000-000000000030"

    before = count_rows(db, "track")

    track1 = {
        "musicbrainz_recording_id": mbid,
        "name": "测试歌曲",
        "duration_ms": 200000,
    }

    track2 = {
        "musicbrainz_recording_id": mbid,
        "name": "测试歌曲（更新）",
        "duration_ms": 210000,
    }

    track_id_1 = track_repository.upsert(
        track1,
        autocommit=False,
    )

    track_id_2 = track_repository.upsert(
        track2,
        autocommit=False,
    )

    after = count_rows(db, "track")

    assert after == before + 1
    assert track_id_1 == track_id_2

    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT name, duration_ms
            FROM track
            WHERE id = %s
            """,
            (track_id_1,),
        )
        row = cursor.fetchone()

    assert row["name"] == "测试歌曲（更新）"
    assert row["duration_ms"] == 210000


def test_track_artist_repository(db):
    artist_repository = ArtistRepository(db)
    album_repository = AlbumRepository(db)
    track_repository = TrackRepository(db)
    relation_repository = TrackArtistRepository(db)

    artist_id = artist_repository.ensure_stub(
        "00000000-0000-0000-0000-000000000040",
        "测试歌手",
        autocommit=False,
    )

    track_id = track_repository.upsert(
        {
            "musicbrainz_recording_id":
                "00000000-0000-0000-0000-000000000041",
            "name": "测试歌曲",
            "duration_ms": 180000,
        },
        autocommit=False,
    )

    before = count_rows(db, "track_artist")

    relation_repository.upsert(
        track_id,
        artist_id,
        "测试歌手",
        "",
        autocommit=False,
    )

    relation_repository.upsert(
        track_id,
        artist_id,
        "测试歌手（更新）",
        " feat. ",
        autocommit=False,
    )

    after = count_rows(db, "track_artist")

    assert after == before + 1

    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT credited_name, join_phrase
            FROM track_artist
            WHERE track_id = %s
              AND artist_id = %s
            """,
            (track_id, artist_id),
        )
        row = cursor.fetchone()

    assert row["credited_name"] == "测试歌手（更新）"
    assert row["join_phrase"] == " feat. "


def test_release_track_repository(db):
    album_repository = AlbumRepository(db)
    release_repository = ReleaseRepository(db)
    track_repository = TrackRepository(db)
    repository = ReleaseTrackRepository(db)

    album_id = album_repository.upsert(
        {
            "musicbrainz_id":
                "00000000-0000-0000-0000-000000000050",
            "name": "测试专辑",
            "release_date": "2001-01-01",
            "primary_type": "Album",
            "secondary_types": [],
        },
        autocommit=False,
    )

    release_id = release_repository.upsert(
        {
            "musicbrainz_id":
                "00000000-0000-0000-0000-000000000051",
            "album_id": album_id,
            "title": "测试发行",
            "release_date": "2001-01-01",
            "country": "TW",
            "status": "Official",
        },
        autocommit=False,
    )

    track_id_1 = track_repository.upsert(
        {
            "musicbrainz_recording_id":
                "00000000-0000-0000-0000-000000000052",
            "name": "歌曲 1",
            "duration_ms": 180000,
        },
        autocommit=False,
    )

    track_id_2 = track_repository.upsert(
        {
            "musicbrainz_recording_id":
                "00000000-0000-0000-0000-000000000053",
            "name": "歌曲 2",
            "duration_ms": 190000,
        },
        autocommit=False,
    )

    before = count_rows(db, "release_track")

    # 第一次写入
    repository.upsert(
        release_id=release_id,
        track_id=track_id_1,
        track_number=1,
        disc_number=1,
        autocommit=False,
    )

    # 同一个 slot 再写一次
    repository.upsert(
        release_id=release_id,
        track_id=track_id_2,
        track_number=1,
        disc_number=1,
        autocommit=False,
    )

    # 不同 track_number：
    # 同一张 release 中应该可以合法存在
    repository.upsert(
        release_id=release_id,
        track_id=track_id_1,
        track_number=2,
        disc_number=1,
        autocommit=False,
    )

    after = count_rows(db, "release_track")

    assert after == before + 2

    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT track_id
            FROM release_track
            WHERE release_id = %s
              AND disc_number = 1
              AND track_number = 1
            """,
            (release_id,),
        )
        row = cursor.fetchone()

    # 同一个 slot 的第二次写入应该更新 track_id
    assert row["track_id"] == track_id_2


def test_release_track_repository_track_number_none(db):
    album_repository = AlbumRepository(db)
    release_repository = ReleaseRepository(db)
    track_repository = TrackRepository(db)
    repository = ReleaseTrackRepository(db)

    album_id = album_repository.upsert(
        {
            "musicbrainz_id":
                "00000000-0000-0000-0000-000000000060",
            "name": "测试专辑",
            "release_date": "2001-01-01",
            "primary_type": "Album",
            "secondary_types": [],
        },
        autocommit=False,
    )

    release_id = release_repository.upsert(
        {
            "musicbrainz_id":
                "00000000-0000-0000-0000-000000000061",
            "album_id": album_id,
            "title": "测试发行",
            "release_date": "2001-01-01",
            "country": "TW",
            "status": "Official",
        },
        autocommit=False,
    )

    track_id = track_repository.upsert(
        {
            "musicbrainz_recording_id":
                "00000000-0000-0000-0000-000000000062",
            "name": "测试歌曲",
            "duration_ms": 180000,
        },
        autocommit=False,
    )

    before = count_rows(db, "release_track")

    # Repository 内部应该 skip，不应该抛异常
    result = repository.upsert(
        release_id=release_id,
        track_id=track_id,
        track_number=None,
        disc_number=1,
        autocommit=False,
    )

    after = count_rows(db, "release_track")

    assert result is None
    assert after == before