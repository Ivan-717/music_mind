from musicbrainz import MusicBrainzClient
from musicbrainz.adapter import MusicBrainzDataAdapter


def main():
    client = MusicBrainzClient(
        user_agent="MusicMind/0.1.0 (your-email@example.com)"
    )

    adapter = MusicBrainzDataAdapter()

    # 1. 搜索 Artist
    result = client.search_artist("周杰伦")

    if not result.get("artists"):
        print("没有找到 Artist")
        return

    artist = result["artists"][0]

    # 2. 转换 Artist
    musicmind_artist = adapter.artist_to_musicmind(artist)

    # 3. 转换 Artist Alias
    musicmind_aliases = adapter.artist_aliases_to_musicmind(artist)

    print("MusicMind Artist：")
    print(musicmind_artist)

    print("\nMusicMind Artist Aliases：")

    for alias in musicmind_aliases:
        print(alias)


if __name__ == "__main__":
    main()