import contextlib
from unittest import mock

import pytest

import mopidy_songhive
import mopidy_songhive.backend
import mopidy_songhive.remote

TRACK = {
    "id": "track-1",
    "title": "Song One",
    "artist_id": "artist-1",
    "album_id": "album-1",
    "track_number": 3,
    "disc_number": 1,
    "duration": 240.5,
    "genre": "rock",
    "release_year": 2001,
    "visibility": "public",
    "artist": {"id": "artist-1", "name": "The Artist"},
    "album": {
        "id": "album-1",
        "title": "The Album",
        "artist_id": "artist-1",
        "artist": {"id": "artist-1", "name": "The Artist"},
        "release_year": 2001,
    },
}

TRACK_2 = {
    "id": "track-2",
    "title": "Song Two",
    "artist_id": "artist-1",
    "album_id": "album-1",
    "track_number": 4,
    "disc_number": 1,
    "duration": 180.0,
    "artist": {"id": "artist-1", "name": "The Artist"},
    "album": {
        "id": "album-1",
        "title": "The Album",
        "artist_id": "artist-1",
        "artist": {"id": "artist-1", "name": "The Artist"},
        "release_year": 2001,
    },
}

ALBUM = {
    "id": "album-1",
    "title": "The Album",
    "artist_id": "artist-1",
    "release_year": 2001,
    "artist": {"id": "artist-1", "name": "The Artist"},
    "tracks": [TRACK, TRACK_2],
}

ARTIST = {
    "id": "artist-1",
    "name": "The Artist",
    "albums": [ALBUM],
    "tracks": [TRACK, TRACK_2],
}

PLAYLIST = {
    "id": "playlist-1",
    "name": "My Playlist",
    "owner_id": "u1",
    "visibility": "private",
}

LIBRARY = {
    "id": "library-1",
    "name": "Music",
    "visibility": "public",
}

PODCAST = {
    "id": "podcast-1",
    "feed_url": "https://podcasts.example.com/feed.xml",
    "title": "Test Podcast",
    "author": "The Host",
    "episode_count": 2,
    "unplayed_count": 2,
}

PODCAST_EPISODE = {
    "id": "episode-1",
    "podcast_id": "podcast-1",
    "guid": "ep-1",
    "title": "Episode One",
    "description": "The first episode",
    "audio_url": "https://cdn.example.com/episodes/1.mp3",
    "audio_type": "audio/mpeg",
    "duration_seconds": 1800,
    "published_at": "2025-09-08T12:00:00Z",
    "episode_number": 1,
    "played": False,
}

PODCAST_EPISODE_2 = {
    "id": "episode-2",
    "podcast_id": "podcast-1",
    "guid": "ep-2",
    "title": "Episode Two",
    "audio_url": "https://cdn.example.com/episodes/2.mp3",
    "duration_seconds": 2400,
    "published_at": "2025-09-01T12:00:00Z",
    "episode_number": 2,
    "played": True,
}

REMOTE_TRACK = {
    "id": "remote-1",
    "canonical_url": "https://other.example.com/tracks/99",
    "object_type": "Audio",
    "resource_type": "track",
    "domain": "other.example.com",
    "actor_url": "https://other.example.com/users/bob",
    "actor_handle": "bob@other.example.com",
    "name": "Remote Song",
    "audio_url": "https://other.example.com/api/v1/stream/99",
    "visibility": "public",
    "url": "/remote/track/remote-1",
}


@pytest.fixture
def config():
    return {
        "songhive": {
            "hostname": "https://songhive.example.com",
            "api_token": "test-token",
            "libraries": "",
            "album_format": "{title}",
            "transcode_format": "",
            "transcode_bitrate": None,
        },
        "proxy": {},
    }


@pytest.fixture
def anon_config(config):
    config = {k: dict(v) for k, v in config.items()}
    config["songhive"]["api_token"] = ""
    return config


@pytest.fixture
def songhive_client(config, mocker):
    mocker.patch(
        "mopidy_songhive.remote.SonghiveClient._check_connection",
        return_value={"id": "u1", "username": "tester"},
    )
    return mopidy_songhive.remote.SonghiveClient(config)


@pytest.fixture
def backend_mock(songhive_client):
    backend = mock.Mock(spec=mopidy_songhive.backend.SonghiveBackend)
    remote = mock.Mock(spec=mopidy_songhive.remote.SonghiveClient)
    remote.hostname = songhive_client.hostname
    remote.token = songhive_client.token
    remote.authenticated = True

    # Mirror the client's parallel fetchers synchronously so providers
    # exercise the same code path against the stubbed getters.
    def _sync_fetch(getter, item_ids, *_, **__):
        out = {}
        for item_id in dict.fromkeys(item_ids):
            with contextlib.suppress(Exception):
                out[item_id] = getter(item_id)
        return out

    remote.fetch_parallel.side_effect = _sync_fetch
    remote.get_tracks_by_ids.side_effect = (
        lambda track_ids, max_workers=8: _sync_fetch(
            remote.get_track, track_ids, max_workers=max_workers
        )
    )
    remote.get_podcast_episodes_by_ids.side_effect = (
        lambda episode_ids, max_workers=8: _sync_fetch(
            remote.get_podcast_episode, episode_ids, max_workers=max_workers
        )
    )
    # Bind the real model/ref builders so providers produce real models.
    for name in (
        "track_ref",
        "album_ref",
        "artist_ref",
        "playlist_ref",
        "library_ref",
        "genre_ref",
        "tag_ref",
        "podcast_ref",
        "podcast_episode_ref",
        "remote_ref",
        "to_track",
        "to_album",
        "to_artist",
        "to_podcast_track",
        "remote_object_track",
        "format_album",
        "is_own_url",
    ):
        setattr(remote, name, getattr(songhive_client, name))
    backend.remote = remote
    return backend
