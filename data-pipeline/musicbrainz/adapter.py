from typing import Any
from datetime import datetime

def normalize_date(value: str | None) -> str | None:
    if not value:
        return None

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m",
        "%Y",
    ):
        try:
            return datetime.strptime(
                value,
                fmt
            ).date().isoformat()

        except ValueError:
            continue

    return None

class MusicBrainzDataAdapter:

    def artist_to_musicmind(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "musicbrainz_id": data["id"],
            "name": data["name"],
            "sort_name": data.get("sort-name"),
            "disambiguation": data.get("disambiguation"),
        }

    def artist_aliases_to_musicmind(
        self,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        aliases = data.get("aliases", [])

        result = []

        for alias in aliases:
            result.append(
                {
                    "name": alias["name"],
                    "locale": alias.get("locale") or "",
                    "is_primary": alias.get("primary", False),
                }
            )

        return result

    def album_to_musicmind(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "musicbrainz_id": data["id"],
            "name": data["title"],
            "release_date": normalize_date(
                 data.get("first-release-date")
            ),
            "primary_type": data.get("primary-type"),
            "secondary_types": data.get("secondary-types", []),
        }

    def album_artists_to_musicmind(
        self,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        artist_credits = data.get("artist-credit", [])

        result = []

        for credit in artist_credits:
            artist = credit.get("artist", {})

            if not artist.get("id"):
                continue

            result.append(
                {
                    "artist_musicbrainz_id": artist["id"],
                    "credited_name": artist.get("name"),
                    "join_phrase": credit.get("joinphrase", ""),
                }
            )

        return result

    def track_to_musicmind(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        recording = data.get("recording", {})

        return {
            "musicbrainz_recording_id": recording["id"],
            "name": recording["title"],
            "duration_ms": recording.get("length"),
        }

    def track_artists_to_musicmind(
        self,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        artist_credits = data.get("artist-credit", [])

        result = []

        for credit in artist_credits:
            artist = credit.get("artist", {})

            if not artist.get("id"):
                continue

            result.append(
                {
                    "artist_musicbrainz_id": artist["id"],
                    "credited_name": artist.get("name"),
                    "join_phrase": credit.get("joinphrase", ""),
                }
            )

        return result

    def release_tracks_to_musicmind(
            self,
            data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        release_musicbrainz_id = data["id"]

        result = []

        for media in data.get("media", []):
            disc_number = media.get("position")

            for track in media.get("tracks", []):
                recording = track.get("recording", {})

                recording_id = recording.get("id")

                if not recording_id:
                    continue

                result.append(
                    {
                        "release_musicbrainz_id": release_musicbrainz_id,
                        "track_musicbrainz_recording_id": recording_id,
                        "track_number": track.get("position"),
                        "disc_number": disc_number,
                    }
                )

        return result

    def release_to_musicmind(
            self,
            data: dict[str, Any],
    ) -> dict[str, Any]:
        release_group = data.get("release-group", {})

        return {
            "musicbrainz_id": data["id"],
            "album_musicbrainz_id": release_group.get("id"),
            "title": data["title"],
            "release_date": normalize_date(
                data.get("date")
            ),
            "country": data.get("country"),
            "status": data.get("status"),
        }