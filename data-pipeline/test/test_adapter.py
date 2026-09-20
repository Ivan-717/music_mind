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

    # 2. 当前先取搜索结果中的第一个 Artist
    artist = result["artists"][0]

    # 3. 打印 Artist 基本信息
    print("Artist 基本信息：")
    print("MBID:", artist.get("id"))
    print("名称:", artist.get("name"))
    print("Sort Name:", artist.get("sort-name"))
    print("Country:", artist.get("country"))
    print("Disambiguation:", artist.get("disambiguation"))

    # 4. 打印 Artist Aliases
    print("\nArtist Aliases：")

    aliases = artist.get("aliases", [])

    if not aliases:
        print("没有 Alias")
    else:
        for alias in aliases:
            print(
                alias.get("name"),
                "|",
                alias.get("locale"),
                "|",
                "primary =",
                alias.get("primary"),
            )

    # 5. 使用 Adapter 转换
    musicmind_artist = adapter.artist_to_musicmind(artist)

    # 6. 打印转换后的 MusicMind Artist
    print("\nMusicMind Artist：")
    print(musicmind_artist)


if __name__ == "__main__":
    main()