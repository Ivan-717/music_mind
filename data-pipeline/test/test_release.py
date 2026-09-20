from musicbrainz import MusicBrainzClient
from musicbrainz.adapter import MusicBrainzDataAdapter


def main():
    client = MusicBrainzClient(
        user_agent="MusicMind/0.1.0 (your-email@example.com)"
    )

    adapter = MusicBrainzDataAdapter()

    release_mbid = "0377c05a-0da4-46f7-a153-52e80e7adac1"

    release = client.get_release(release_mbid)

    musicmind_release = adapter.release_to_musicmind(
        release
    )

    print("MusicMind Release：")
    print(musicmind_release)


if __name__ == "__main__":
    main()