import time
import requests

from config.settings import MUSICBRAINZ_CONFIG


BASE_URL = "https://musicbrainz.org/ws/2"

HEADERS = {
    "User-Agent": MUSICBRAINZ_CONFIG["user_agent"]
}


def request_json(url: str, params: dict):
    """
    请求 MusicBrainz API。
    遇到 503 时最多重试 3 次。
    """
    for attempt in range(3):
        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=10,
        )

        if response.status_code == 503:
            print(
                f"MusicBrainz 暂时不可用，"
                f"第 {attempt + 1} 次请求失败，准备重试..."
            )

            if attempt < 2:
                time.sleep(2)

            continue

        response.raise_for_status()

        return response.json()

    raise RuntimeError("MusicBrainz 连续 3 次请求失败，请稍后再试。")


def search_artist(name: str):
    """
    根据艺术家名称搜索 Artist。
    """
    url = f"{BASE_URL}/artist"

    params = {
        "query": f'artist:"{name}"',
        "fmt": "json",
        "limit": 5,
    }

    return request_json(url, params)


def get_artist_releases(artist_id: str):
    """
    根据 Artist MBID 查询该艺术家的 Release。
    """
    url = f"{BASE_URL}/release"

    params = {
        "artist": artist_id,
        "fmt": "json",
        "limit": 10,
    }

    return request_json(url, params)


def get_release_detail(release_id: str):
    """
    查询 Release 详情。

    获取：
    - Release Group
    - Media
    - Track
    - Recording
    - Artist Credit
    """
    url = f"{BASE_URL}/release/{release_id}"

    params = {
        "fmt": "json",
        "inc": "recordings+release-groups+media+artist-credits",
    }

    return request_json(url, params)


def get_recording_detail(recording_id: str):
    """
    查询 Recording 详情。

    获取 Recording 的 Artist Credit。
    """
    url = f"{BASE_URL}/recording/{recording_id}"

    params = {
        "fmt": "json",
        "inc": "artist-credits",
    }

    return request_json(url, params)


def main():
    # ============================================================
    # 1. 搜索周杰伦
    # ============================================================

    artist_result = search_artist("周杰伦")

    artists = artist_result.get("artists", [])

    if not artists:
        print("没有找到艺术家")
        return

    artist = artists[0]

    artist_id = artist.get("id")

    print("Artist 信息")
    print("=" * 60)
    print("id:", artist_id)
    print("name:", artist.get("name"))
    print("sort-name:", artist.get("sort-name"))
    print("country:", artist.get("country"))
    print("disambiguation:", artist.get("disambiguation"))

    # ============================================================
    # 2. 查询 Artist 的 Release
    # ============================================================

    print("\n正在查询 Release...")

    release_result = get_artist_releases(artist_id)

    releases = release_result.get("releases", [])

    print("\nRelease 数量：", len(releases))

    # ============================================================
    # 3. 找到《范特西》
    # ============================================================

    target_release = None

    for release in releases:
        if release.get("title") == "范特西":
            target_release = release
            break

    if target_release is None:
        print("没有找到《范特西》")
        return

    release_id = target_release.get("id")

    print("\n准备查询《范特西》")
    print("=" * 60)
    print("Release ID:", release_id)

    # ============================================================
    # 4. 查询 Release 详情
    # ============================================================

    release_detail = get_release_detail(release_id)

    print("\nRelease 信息")
    print("=" * 60)
    print("id:", release_detail.get("id"))
    print("title:", release_detail.get("title"))
    print("date:", release_detail.get("date"))
    print("country:", release_detail.get("country"))
    print("status:", release_detail.get("status"))

    # ============================================================
    # 5. Release Group
    # ============================================================

    release_group = release_detail.get("release-group")

    print("\nRelease Group")
    print("=" * 60)

    if release_group:
        print("id:", release_group.get("id"))
        print("title:", release_group.get("title"))
        print("primary-type:", release_group.get("primary-type"))
        print(
            "first-release-date:",
            release_group.get("first-release-date")
        )

    # ============================================================
    # 6. 查看 Release Artist Credit
    # ============================================================

    print("\nRelease Artist Credit")
    print("=" * 60)

    release_artist_credit = release_detail.get("artist-credit", [])

    for credit in release_artist_credit:
        credited_artist = credit.get("artist")

        if credited_artist:
            print(
                "artist:",
                credited_artist.get("name")
            )

            print(
                "artist id:",
                credited_artist.get("id")
            )

        print(
            "join phrase:",
            credit.get("joinphrase")
        )

    # ============================================================
    # 7. 获取 Track
    # ============================================================

    media_list = release_detail.get("media", [])

    print("\nTrack 列表")
    print("=" * 60)

    target_recording_id = None

    for media in media_list:
        tracks = media.get("tracks", [])

        for track in tracks:
            position = track.get("position")
            title = track.get("title")

            print("-" * 60)
            print("Track position:", position)
            print("Track title:", title)

            recording = track.get("recording")

            if recording:
                recording_id = recording.get("id")
                recording_title = recording.get("title")
                length = recording.get("length")

                print("Recording ID:", recording_id)
                print("Recording title:", recording_title)
                print("Length:", length)

                # 找到第一首歌《愛在西元前》
                if title == "愛在西元前":
                    target_recording_id = recording_id

    # ============================================================
    # 8. 查询《愛在西元前》的 Recording
    # ============================================================

    if target_recording_id is None:
        print("\n没有找到《愛在西元前》的 Recording")
        return

    print("\n")
    print("=" * 60)
    print("查询《愛在西元前》的 Recording")
    print("=" * 60)

    print("Recording ID:", target_recording_id)

    recording_detail = get_recording_detail(target_recording_id)

    print("\nRecording 信息")
    print("=" * 60)

    print("id:", recording_detail.get("id"))
    print("title:", recording_detail.get("title"))
    print("length:", recording_detail.get("length"))

    # ============================================================
    # 9. Recording Artist Credit
    # ============================================================

    print("\nRecording Artist Credit")
    print("=" * 60)

    recording_artist_credit = recording_detail.get(
        "artist-credit",
        []
    )

    if not recording_artist_credit:
        print("没有 Artist Credit")
        return

    for credit in recording_artist_credit:
        credited_artist = credit.get("artist")

        if credited_artist:
            print(
                "artist:",
                credited_artist.get("name")
            )

            print(
                "artist id:",
                credited_artist.get("id")
            )

        print(
            "credited name:",
            credit.get("name")
        )

        print(
            "join phrase:",
            credit.get("joinphrase")
        )


if __name__ == "__main__":
    main()