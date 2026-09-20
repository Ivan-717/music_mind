from musicbrainz import MusicBrainzClient
from musicbrainz.adapter import MusicBrainzDataAdapter


def main():
    client = MusicBrainzClient(
        user_agent="MusicMind/0.1.0 (your-email@example.com)"
    )

    adapter = MusicBrainzDataAdapter()

    release_group_mbid = "732b78cb-9f7d-383d-86cc-5cf7e43c9658"

    # 1. 获取 Release Group
    release_group = client.get_release_group(
        release_group_mbid
    )

    # 2. 转换 Album
    musicmind_album = adapter.album_to_musicmind(
        release_group
    )

    # 3. 转换 AlbumArtist
    musicmind_album_artists = (
        adapter.album_artists_to_musicmind(
            release_group
        )
    )

    print("MusicMind Album：")
    print(musicmind_album)

    print("\nMusicMind Album Artists：")

    for album_artist in musicmind_album_artists:
        print(album_artist)


if __name__ == "__main__":
    main()