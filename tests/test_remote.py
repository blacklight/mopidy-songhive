import pytest
from conftest import (
    ALBUM,
    ARTIST,
    PODCAST,
    PODCAST_EPISODE,
    REMOTE_TRACK,
    TRACK,
    TRACK_2,
)

from mopidy_songhive.http import SonghiveHttpError


def test_hostname_normalized(anon_config):
    from unittest import mock

    from mopidy_songhive.remote import SonghiveClient

    anon_config["songhive"]["hostname"] = "songhive.example.com/"
    with mock.patch.object(
        SonghiveClient, "_check_connection", return_value=None
    ):
        client = SonghiveClient(anon_config)
    assert client.hostname == "https://songhive.example.com"
    assert client.token is None


def test_to_track(songhive_client):
    track = songhive_client.to_track(TRACK)
    assert track.uri == "songhive:track:track-1"
    assert track.name == "Song One"
    assert track.track_no == 3
    assert track.disc_no == 1
    assert track.length == 240500
    assert track.genre == "rock"
    assert track.date == "2001"
    assert next(iter(track.artists)).name == "The Artist"
    assert track.album.name == "The Album"
    assert next(iter(track.album.artists)).name == "The Artist"


def test_to_track_without_album(songhive_client):
    data = dict(TRACK, album_id=None, album=None)
    track = songhive_client.to_track(data)
    assert track.album is None
    assert next(iter(track.artists)).uri == "songhive:artist:artist-1"


def test_get_libraries_allowlist(config, mocker):
    from mopidy_songhive.remote import SonghiveClient

    config["songhive"]["libraries"] = "Music, Podcasts"
    mocker.patch.object(SonghiveClient, "_check_connection")
    client = SonghiveClient(config)
    client.http = mocker.Mock()
    client.http.get_all.return_value = [
        {"id": "l1", "name": "Music"},
        {"id": "l2", "name": "Other"},
    ]

    libs = client.get_libraries()
    assert [lib["name"] for lib in libs] == ["Music"]


def test_get_favorite_tracks_authenticated(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [TRACK]
    tracks = songhive_client.get_favorite_tracks()
    args, kwargs = songhive_client.http.get_all.call_args
    assert args[0] == "/tracks/"
    assert kwargs["params"]["favorited"] == "true"
    assert tracks == [TRACK]


def test_get_favorite_tracks_anonymous(anon_config, mocker):
    from mopidy_songhive.remote import SonghiveClient

    mocker.patch.object(SonghiveClient, "_check_connection")
    client = SonghiveClient(anon_config)
    client.http = mocker.Mock()
    client.http.authenticated = False
    assert client.get_favorite_tracks() == []
    client.http.get_all.assert_not_called()


def test_search(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = {
        "sections": [
            {"entity": "tracks", "items": [TRACK]},
            {"entity": "albums", "items": [ALBUM]},
        ]
    }
    result = songhive_client.search("hello")
    assert result == {"tracks": [TRACK], "albums": [ALBUM]}
    _, kwargs = songhive_client.http.get.call_args
    assert kwargs["params"]["q"] == "hello"


def test_search_failure_returns_empty(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.side_effect = SonghiveHttpError(500, "boom")
    assert songhive_client.search("x") == {}


def test_resolve_url_local_track(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    result = songhive_client.resolve_url(
        "https://songhive.example.com/tracks/track-1"
    )
    assert result == "songhive:track:track-1"
    songhive_client.http.get.assert_not_called()


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/albums/album-1", "songhive:album:album-1"),
        ("/artists/artist-1", "songhive:artist:artist-1"),
        ("/playlists/playlist-1", "songhive:playlist:playlist-1"),
        ("/libraries/library-1", "songhive:library:library-1"),
        ("/genres/rock", "songhive:genre:rock"),
        ("/tags/live", "songhive:tag:live"),
        ("/favorites", "songhive:favorites"),
        ("/podcasts", "songhive:podcasts"),
        ("/podcasts/podcast-1", "songhive:podcast:podcast-1"),
        ("/remote/track/remote-1", "songhive:remote:remote-1"),
        ("/remote/playlist/remote-9", "songhive:remote:remote-9"),
        ("/activities/@bob/remote-1", "songhive:remote:remote-1"),
    ],
)
def test_resolve_url_local_routes(songhive_client, mocker, path, expected):
    songhive_client.http = mocker.Mock()
    url = f"https://songhive.example.com{path}"
    assert songhive_client.resolve_url(url) == expected


def test_resolve_url_remote_object(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = {
        "kind": "object",
        "object": REMOTE_TRACK,
    }
    result = songhive_client.resolve_url("https://other.example.com/tracks/99")
    assert result == "songhive:remote:remote-1"
    args, kwargs = songhive_client.http.get.call_args
    assert args[0] == "/remote/lookup"
    assert kwargs["params"]["input"] == "https://other.example.com/tracks/99"


def test_resolve_url_remote_local_kind(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = {
        "kind": "local",
        "url": "https://songhive.example.com/tracks/track-5",
    }
    result = songhive_client.resolve_url(
        "https://other.example.com/redirects-to-local"
    )
    assert result == "songhive:track:track-5"


def test_resolve_url_unsupported(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.side_effect = SonghiveHttpError(404, "nope")
    assert (
        songhive_client.resolve_url("https://other.example.com/none") is None
    )
    assert songhive_client.resolve_url("ftp://x") is None
    assert songhive_client.resolve_url("not-a-url") is None


def test_stream_url(songhive_client):
    assert songhive_client.stream_url("track-1") == (
        "https://songhive.example.com/api/v1/stream/track-1"
    )


def test_stream_url_transcode(config, mocker):
    from mopidy_songhive.remote import SonghiveClient

    config["songhive"]["transcode_format"] = "mp3"
    config["songhive"]["transcode_bitrate"] = 192
    mocker.patch.object(SonghiveClient, "_check_connection")
    client = SonghiveClient(config)
    url = client.stream_url("t1")
    assert url.startswith("https://songhive.example.com/api/v1/stream/t1?")
    assert "format=mp3" in url
    assert "bitrate=192k" in url


def test_is_own_url(songhive_client):
    assert songhive_client.is_own_url(
        "https://songhive.example.com/api/v1/stream/1"
    )
    assert not songhive_client.is_own_url("https://other.example.com/x")
    assert not songhive_client.is_own_url(
        "https://songhive.example.com.evil.com/x"
    )
    assert not songhive_client.is_own_url("")
    assert not songhive_client.is_own_url(None)


def test_playlist_mutations(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.create_playlist("New")
    songhive_client.http.post.assert_called_with(
        "/playlists/",
        payload={"name": "New"},
        params={"visibility": "private"},
    )
    songhive_client.add_playlist_tracks("p1", ["t1", "t2"])
    songhive_client.http.post.assert_called_with(
        "/playlists/p1/tracks",
        payload={"track_ids": ["t1", "t2"], "allow_duplicates": True},
    )
    songhive_client.remove_playlist_tracks("p1", ["t1"])
    songhive_client.http.post.assert_called_with(
        "/playlists/p1/tracks/remove", payload={"track_ids": ["t1"]}
    )
    songhive_client.reorder_playlist_tracks("p1", ["t2"], position=1)
    songhive_client.http.post.assert_called_with(
        "/playlists/p1/tracks/reorder",
        payload={"track_ids": ["t2"], "position": 1},
    )
    songhive_client.rename_playlist("p1", "Renamed")
    songhive_client.http.patch.assert_called_with(
        "/playlists/p1", payload={"name": "Renamed"}
    )
    songhive_client.delete_playlist("p1")
    songhive_client.http.delete.assert_called_with("/playlists/p1")


def test_add_playlist_tracks_409_tolerated(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.post.side_effect = SonghiveHttpError(409, "conflict")
    # allow_duplicates=False → swallow; allow_duplicates=True → raise.
    songhive_client.add_playlist_tracks("p1", ["t1"], allow_duplicates=False)
    with pytest.raises(SonghiveHttpError):
        songhive_client.add_playlist_tracks("p1", ["t1"])


def test_get_remote_object_unwraps(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = {"object": REMOTE_TRACK}
    assert songhive_client.get_remote_object("remote-1") == REMOTE_TRACK
    songhive_client.http.get.return_value = REMOTE_TRACK
    assert songhive_client.get_remote_object("remote-1") == REMOTE_TRACK


def test_get_podcasts_authenticated(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [PODCAST]
    podcasts = songhive_client.get_podcasts()
    args, kwargs = songhive_client.http.get_all.call_args
    assert args[0] == "/podcasts/"
    assert kwargs["params"]["sort_by"] == "latest"
    assert podcasts == [PODCAST]


def test_get_podcasts_anonymous(anon_config, mocker):
    from mopidy_songhive.remote import SonghiveClient

    mocker.patch.object(SonghiveClient, "_check_connection")
    client = SonghiveClient(anon_config)
    client.http = mocker.Mock()
    client.http.authenticated = False
    assert client.get_podcasts() == []
    client.http.get_all.assert_not_called()


def test_get_podcast_episodes(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [PODCAST_EPISODE]
    episodes = songhive_client.get_podcast_episodes("podcast-1")
    args, kwargs = songhive_client.http.get_all.call_args
    assert args[0] == "/podcasts/podcast-1/episodes"
    assert kwargs["params"]["sort"] == "newest"
    assert episodes == [PODCAST_EPISODE]


def test_to_podcast_track(songhive_client):
    track = songhive_client.to_podcast_track(PODCAST_EPISODE, PODCAST)
    assert track.uri == "songhive:podcast_episode:episode-1"
    assert track.name == "Episode One"
    assert track.album.name == "Test Podcast"
    assert track.album.uri == "songhive:podcast:podcast-1"
    assert next(iter(track.artists)).name == "The Host"
    assert track.track_no == 1
    assert track.date == "2025-09-08"
    assert track.length == 1800000
    assert track.comment == "The first episode"
    assert track.genre == "Podcast"


def test_to_podcast_track_without_podcast(songhive_client):
    track = songhive_client.to_podcast_track(PODCAST_EPISODE)
    # The album still gets its URI from the episode's podcast_id.
    assert track.album.uri == "songhive:podcast:podcast-1"
    assert track.album.name is None
    assert list(track.artists) == []


def test_get_image_podcast_episode_falls_back_to_show(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.side_effect = lambda path, params=None: (
        {"id": "episode-1", "podcast_id": "podcast-1"}
        if path == "/podcasts/episodes/episode-1"
        else {"id": "podcast-1", "image_url": "/covers/show.jpg"}
    )
    images = songhive_client.get_image("podcast_episode", "episode-1")
    assert images[0].uri == "https://songhive.example.com/covers/show.jpg"


def test_remote_object_track(songhive_client):
    track = songhive_client.remote_object_track(REMOTE_TRACK)
    assert track.uri == "songhive:remote:remote-1"
    assert track.name == "Remote Song"
    assert next(iter(track.artists)).name == "bob@other.example.com"


def test_get_image(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = {
        "id": "album-1",
        "cover_url": "/covers/a1.jpg",
    }
    images = songhive_client.get_image("album", "album-1")
    assert len(images) == 1
    assert images[0].uri == "https://songhive.example.com/covers/a1.jpg"


def test_get_image_none(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = {"id": "artist-1"}
    assert songhive_client.get_image("artist", "artist-1") == []
    songhive_client.http.get.side_effect = SonghiveHttpError(404, "nope")
    assert songhive_client.get_image("album", "x") == []


def test_remote_ref_types(songhive_client):
    ref = songhive_client.remote_ref(REMOTE_TRACK)
    assert ref.type == ref.TRACK
    ref = songhive_client.remote_ref(
        dict(REMOTE_TRACK, resource_type="album", audio_url=None)
    )
    assert ref.type == ref.ALBUM
    ref = songhive_client.remote_ref(
        dict(REMOTE_TRACK, resource_type=None, audio_url=None)
    )
    assert ref.type == ref.DIRECTORY


def test_get_artist_tracks_sorted(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [TRACK_2, TRACK]
    tracks = songhive_client.get_artist_tracks("artist-1")
    assert [t["id"] for t in tracks] == ["track-1", "track-2"]


def test_get_album_tracks_sorted(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = dict(
        ALBUM, tracks=[TRACK_2, TRACK]
    )
    tracks = songhive_client.get_album_tracks("album-1")
    assert [t["id"] for t in tracks] == ["track-1", "track-2"]


def test_get_track_cached(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = TRACK
    assert songhive_client.get_track("track-1") == TRACK
    assert songhive_client.get_track("track-1") == TRACK
    songhive_client.http.get.assert_called_once()


def test_get_album_cached(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = ALBUM
    songhive_client.get_album("album-1")
    songhive_client.get_album("album-1")
    songhive_client.http.get.assert_called_once()


def test_get_albums_kwargs_have_distinct_cache(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = []
    songhive_client.get_albums()
    songhive_client.get_albums(genre="rock")
    songhive_client.get_albums()
    songhive_client.get_albums(genre="rock")
    assert songhive_client.http.get_all.call_count == 2


def test_playlist_tracks_invalidated_on_add(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [TRACK]
    songhive_client.get_playlist_tracks("p1")
    assert songhive_client.http.get_all.call_count == 1

    songhive_client.add_playlist_tracks("p1", ["t9"])
    songhive_client.get_playlist_tracks("p1")
    assert songhive_client.http.get_all.call_count == 2


def test_playlists_invalidated_on_create_and_delete(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = []
    songhive_client.get_playlists()
    assert songhive_client.http.get_all.call_count == 1

    songhive_client.create_playlist("New")
    songhive_client.get_playlists()
    assert songhive_client.http.get_all.call_count == 2

    songhive_client.delete_playlist("p1")
    songhive_client.get_playlists()
    assert songhive_client.http.get_all.call_count == 3


def test_remote_lookup_cached(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = {
        "kind": "object",
        "object": REMOTE_TRACK,
    }
    url = "https://other.example.com/tracks/99"
    songhive_client.resolve_url(url)
    songhive_client.resolve_url(url)
    songhive_client.http.get.assert_called_once()


def test_get_remote_object_cached(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = {"object": REMOTE_TRACK}
    songhive_client.get_remote_object("remote-1")
    songhive_client.get_remote_object("remote-1")
    songhive_client.http.get.assert_called_once()


def test_get_tracks_by_ids(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.side_effect = lambda path, params=None: dict(
        TRACK, id=path.rsplit("/", 1)[-1]
    )
    result = songhive_client.get_tracks_by_ids(
        ["t1", "t2", "t1"], max_workers=2
    )
    assert set(result) == {"t1", "t2"}
    assert result["t1"]["id"] == "t1"
    # Deduped: t1 only fetched once.
    assert songhive_client.http.get.call_count == 2


def test_fetch_parallel_skips_failures(songhive_client, mocker):
    songhive_client.http = mocker.Mock()

    def fake_get(path, params=None):
        if "bad" in path:
            raise SonghiveHttpError(404, "gone")
        return TRACK

    songhive_client.http.get.side_effect = fake_get
    result = songhive_client.get_tracks_by_ids(
        ["t1", "bad", "t2"], max_workers=3
    )
    assert set(result) == {"t1", "t2"}


def test_fetch_parallel_empty(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    assert songhive_client.get_tracks_by_ids([]) == {}
    songhive_client.http.get.assert_not_called()


def test_collection_tracks_seed_track_cache(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [TRACK, TRACK_2]

    songhive_client.get_library_tracks("library-1")

    # The listing's payloads are cached, so per-track lookups are free.
    assert songhive_client.get_track("track-1") == TRACK
    assert songhive_client.get_track("track-2") == TRACK_2
    songhive_client.http.get.assert_not_called()


def test_get_tracks_seeds_track_cache(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [TRACK]

    songhive_client.get_genre_tracks("rock")

    assert songhive_client.get_track("track-1") == TRACK
    songhive_client.http.get.assert_not_called()


def test_playlist_tracks_seed_track_cache(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [TRACK]

    songhive_client.get_playlist_tracks("playlist-1")

    assert songhive_client.get_track("track-1") == TRACK
    songhive_client.http.get.assert_not_called()


def test_album_tracks_seed_track_cache(songhive_client, mocker):
    embedded = [
        {k: v for k, v in TRACK.items() if k not in ("artist", "album")},
        {k: v for k, v in TRACK_2.items() if k not in ("artist", "album")},
    ]
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = dict(ALBUM, tracks=embedded)

    songhive_client.get_album("album-1")

    track = songhive_client.get_track("track-1")
    songhive_client.http.get.assert_called_once()
    # Embedded payloads are enriched with the parent album's context.
    assert track["album"]["title"] == "The Album"
    assert track["artist"]["name"] == "The Artist"


def test_artist_tracks_seed_track_cache(songhive_client, mocker):
    embedded = [
        {k: v for k, v in TRACK.items() if k != "artist"},
    ]
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = dict(ARTIST, tracks=embedded)

    songhive_client.get_artist("artist-1")

    track = songhive_client.get_track("track-1")
    songhive_client.http.get.assert_called_once()
    assert track["artist"]["name"] == "The Artist"


def test_podcast_episodes_seed_episode_cache(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [PODCAST_EPISODE]

    songhive_client.get_podcast_episodes("podcast-1")

    assert songhive_client.get_podcast_episode("episode-1") == (
        PODCAST_EPISODE
    )
    songhive_client.http.get.assert_not_called()


def test_get_track_fresh_bypasses_cache(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get.return_value = TRACK

    songhive_client.get_track("track-1")
    songhive_client.get_track("track-1", fresh=True)

    assert songhive_client.http.get.call_count == 2


def test_get_track_404_invalidates_cache(songhive_client, mocker):
    songhive_client.http = mocker.Mock()
    songhive_client.http.get_all.return_value = [TRACK]
    songhive_client.get_library_tracks("library-1")

    songhive_client.http.get.side_effect = SonghiveHttpError(404, "gone")
    with pytest.raises(SonghiveHttpError):
        songhive_client.get_track("track-1", fresh=True)

    # The ghost entry is gone — a later lookup hits the API again.
    songhive_client.http.get.side_effect = None
    songhive_client.http.get.return_value = TRACK
    songhive_client.http.get.reset_mock()
    assert songhive_client.get_track("track-1") == TRACK
    songhive_client.http.get.assert_called_once()


def _client_with_cache_dir(config, mocker, cache_dir):
    from mopidy_songhive.remote import SonghiveClient

    config["core"] = {"cache_dir": str(cache_dir)}
    mocker.patch.object(SonghiveClient, "_check_connection")
    return SonghiveClient(config)


def test_metadata_cache_persists_across_clients(config, mocker, tmp_path):
    client = _client_with_cache_dir(config, mocker, tmp_path)
    client.http = mocker.Mock()
    client.http.get.return_value = TRACK
    client.get_track("track-1")
    client.http.get.assert_called_once()

    # A new client over the same cache dir serves the track from disk.
    restarted = _client_with_cache_dir(config, mocker, tmp_path)
    restarted.http = mocker.Mock()
    assert restarted.get_track("track-1") == TRACK
    restarted.http.get.assert_not_called()
