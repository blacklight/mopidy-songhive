import mopidy
import pytest
from conftest import ALBUM, ARTIST, LIBRARY, REMOTE_TRACK, TRACK, TRACK_2

from mopidy_songhive.library import SonghiveLibraryProvider


@pytest.fixture
def provider(backend_mock):
    return SonghiveLibraryProvider(backend=backend_mock)


def test_browse_root(provider, backend_mock):
    refs = provider.browse("songhive:")
    names = {r.name for r in refs}
    assert names == {
        "Libraries",
        "Playlists",
        "Artists",
        "Albums",
        "Favorites",
        "Genres",
        "Tags",
    }
    assert all(r.type == mopidy.models.Ref.DIRECTORY for r in refs)


def test_browse_root_hides_favorites_when_anonymous(provider, backend_mock):
    backend_mock.remote.authenticated = False
    refs = provider.browse("songhive:")
    assert "Favorites" not in {r.name for r in refs}


def test_browse_libraries(provider, backend_mock):
    backend_mock.remote.get_libraries.return_value = [LIBRARY]
    refs = provider.browse("songhive:libraries")
    assert refs == [
        mopidy.models.Ref.directory(
            uri="songhive:library:library-1", name="Music"
        )
    ]


def test_browse_library_tracks(provider, backend_mock):
    backend_mock.remote.get_library_tracks.return_value = [TRACK, TRACK_2]
    refs = provider.browse("songhive:library:library-1")
    assert [r.uri for r in refs] == [
        "songhive:track:track-1",
        "songhive:track:track-2",
    ]
    assert all(r.type == mopidy.models.Ref.TRACK for r in refs)


def test_browse_artists(provider, backend_mock):
    backend_mock.remote.get_artists.return_value = [ARTIST]
    refs = provider.browse("songhive:artists")
    assert refs == [
        mopidy.models.Ref.artist(
            uri="songhive:artist:artist-1", name="The Artist"
        )
    ]


def test_browse_artist(provider, backend_mock):
    backend_mock.remote.get_artist.return_value = ARTIST
    refs = provider.browse("songhive:artist:artist-1")
    # Albums first; both tracks belong to the album so no singles appear.
    assert refs == [
        mopidy.models.Ref.album(uri="songhive:album:album-1", name="The Album")
    ]


def test_browse_artist_single(provider, backend_mock):
    single = dict(TRACK, album_id=None, album=None)
    backend_mock.remote.get_artist.return_value = dict(ARTIST, tracks=[single])
    refs = provider.browse("songhive:artist:artist-1")
    assert (
        mopidy.models.Ref.track(uri="songhive:track:track-1", name="Song One")
        in refs
    )


def test_browse_albums(provider, backend_mock):
    backend_mock.remote.get_albums.return_value = [ALBUM]
    refs = provider.browse("songhive:albums")
    assert refs == [
        mopidy.models.Ref.album(uri="songhive:album:album-1", name="The Album")
    ]


def test_browse_genres(provider, backend_mock):
    backend_mock.remote.get_genres.return_value = [
        {"name": "rock", "item_count": 5}
    ]
    refs = provider.browse("songhive:genres")
    assert refs == [
        mopidy.models.Ref.directory(uri="songhive:genre:rock", name="rock")
    ]


def test_browse_genre(provider, backend_mock):
    backend_mock.remote.get_genre_albums.return_value = [ALBUM]
    backend_mock.remote.get_genre_tracks.return_value = [TRACK]
    refs = provider.browse("songhive:genre:rock")
    assert {r.uri for r in refs} == {
        "songhive:album:album-1",
        "songhive:track:track-1",
    }


def test_browse_tags(provider, backend_mock):
    backend_mock.remote.get_tags.return_value = [
        {"name": "live", "item_count": 3}
    ]
    refs = provider.browse("songhive:tags")
    assert refs == [
        mopidy.models.Ref.directory(uri="songhive:tag:live", name="live")
    ]


def test_browse_tag(provider, backend_mock):
    backend_mock.remote.get_tag_tracks.return_value = [TRACK]
    backend_mock.remote.get_tag_items.return_value = [
        {"type": "track", "id": "track-1"},
        {"type": "album", "id": "album-1"},
        {"type": "activity", "id": "act-1"},
    ]
    backend_mock.remote.get_album.return_value = ALBUM
    refs = provider.browse("songhive:tag:live")
    assert {r.uri for r in refs} == {
        "songhive:track:track-1",
        "songhive:album:album-1",
    }


def test_lookup_track(provider, backend_mock):
    backend_mock.remote.get_track.return_value = TRACK
    tracks = provider.lookup("songhive:track:track-1")
    assert len(tracks) == 1
    track = tracks[0]
    assert track.uri == "songhive:track:track-1"
    assert track.name == "Song One"
    assert track.track_no == 3
    assert track.disc_no == 1
    assert track.genre == "rock"
    assert track.date == "2001"
    assert track.length == 240500
    assert next(iter(track.artists)).name == "The Artist"
    assert track.album.name == "The Album"


def test_lookup_album(provider, backend_mock):
    backend_mock.remote.get_album_tracks.return_value = [TRACK, TRACK_2]
    tracks = provider.lookup("songhive:album:album-1")
    assert [t.uri for t in tracks] == [
        "songhive:track:track-1",
        "songhive:track:track-2",
    ]


def test_lookup_playlist(provider, backend_mock):
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK_2, TRACK]
    tracks = provider.lookup("songhive:playlist:playlist-1")
    assert [t.uri for t in tracks] == [
        "songhive:track:track-2",
        "songhive:track:track-1",
    ]


def test_lookup_favorites(provider, backend_mock):
    backend_mock.remote.get_favorite_tracks.return_value = [TRACK]
    tracks = provider.lookup("songhive:favorites")
    assert [t.uri for t in tracks] == ["songhive:track:track-1"]


def test_lookup_remote(provider, backend_mock):
    backend_mock.remote.get_remote_object.return_value = REMOTE_TRACK
    tracks = provider.lookup("songhive:remote:remote-1")
    assert len(tracks) == 1
    assert tracks[0].uri == "songhive:remote:remote-1"
    assert tracks[0].name == "Remote Song"


def test_lookup_remote_without_audio(provider, backend_mock):
    backend_mock.remote.get_remote_object.return_value = dict(
        REMOTE_TRACK, audio_url=None
    )
    assert provider.lookup("songhive:remote:remote-1") == []


def test_lookup_embedded_local_url(provider, backend_mock):
    backend_mock.remote.get_track.return_value = TRACK
    backend_mock.remote.resolve_url.return_value = "songhive:track:track-1"
    tracks = provider.lookup(
        "songhive:https://songhive.example.com/tracks/track-1"
    )
    backend_mock.remote.resolve_url.assert_called_once_with(
        "https://songhive.example.com/tracks/track-1"
    )
    assert [t.uri for t in tracks] == ["songhive:track:track-1"]


def test_lookup_embedded_remote_url(provider, backend_mock):
    backend_mock.remote.resolve_url.return_value = "songhive:remote:remote-1"
    backend_mock.remote.get_remote_object.return_value = REMOTE_TRACK
    tracks = provider.lookup("songhive:https://other.example.com/tracks/99")
    assert [t.uri for t in tracks] == ["songhive:remote:remote-1"]


def test_search(provider, backend_mock):
    backend_mock.remote.get_tracks.return_value = [TRACK]
    backend_mock.remote.get_albums.return_value = [ALBUM]
    backend_mock.remote.get_artists.return_value = [ARTIST]
    backend_mock.remote.search.return_value = {}

    result = provider.search({"any": ["the"]})

    assert result.uri == "songhive:search"
    assert [t.name for t in result.tracks] == ["Song One"]
    assert [a.name for a in result.albums] == ["The Album"]
    assert [a.name for a in result.artists] == ["The Artist"]

    result = provider.search({"any": ["song"]})
    assert [t.name for t in result.tracks] == ["Song One"]
    assert list(result.albums) == []
    assert list(result.artists) == []


def test_search_filters_by_field(provider, backend_mock):
    backend_mock.remote.get_tracks.return_value = [TRACK]
    backend_mock.remote.get_albums.return_value = []
    backend_mock.remote.get_artists.return_value = []
    backend_mock.remote.search.return_value = {}

    result = provider.search({"track_name": ["nope"]})
    assert list(result.tracks) == []

    result = provider.search({"artist": ["The Artist"]})
    assert [t.name for t in result.tracks] == ["Song One"]


def test_search_exact(provider, backend_mock):
    backend_mock.remote.get_tracks.return_value = [TRACK]
    backend_mock.remote.get_albums.return_value = []
    backend_mock.remote.get_artists.return_value = [ARTIST]
    backend_mock.remote.search.return_value = {}

    result = provider.search({"artist": ["The Art"]}, exact=True)
    assert list(result.tracks) == []
    assert list(result.artists) == []

    result = provider.search({"artist": ["The Artist"]}, exact=True)
    assert [t.name for t in result.tracks] == ["Song One"]
    assert [a.name for a in result.artists] == ["The Artist"]


def test_search_scoped_to_other_scheme_returns_none(provider):
    result = provider.search({"any": ["x"]}, uris=["spotify:albums"])
    assert result is None


def test_search_includes_remote_tracks(provider, backend_mock):
    backend_mock.remote.get_tracks.return_value = []
    backend_mock.remote.get_albums.return_value = []
    backend_mock.remote.get_artists.return_value = []
    backend_mock.remote.search.return_value = {
        "remote": [{"type": "track", "id": "remote-1"}]
    }
    backend_mock.remote.get_remote_object.return_value = REMOTE_TRACK

    result = provider.search({"any": ["remote"]})
    assert [t.uri for t in result.tracks] == ["songhive:remote:remote-1"]


def test_get_distinct(provider, backend_mock):
    backend_mock.remote.get_artists.return_value = [ARTIST]
    backend_mock.remote.get_albums.return_value = [ALBUM]
    backend_mock.remote.get_genres.return_value = [{"name": "rock"}]

    assert provider.get_distinct("artist") == {"The Artist"}
    assert provider.get_distinct("album") == {"The Album"}
    assert provider.get_distinct("genre") == {"rock"}
    assert provider.get_distinct("composer") == set()


def test_get_images(provider, backend_mock):
    backend_mock.remote.get_image.return_value = [
        mopidy.models.Image(uri="https://songhive.example.com/img.jpg")
    ]
    images = provider.get_images(["songhive:track:track-1"])
    backend_mock.remote.get_image.assert_called_once_with("track", "track-1")
    assert images["songhive:track:track-1"][0].uri.endswith("img.jpg")


def test_lookup_many_tracks(provider, backend_mock):
    backend_mock.remote.get_track.side_effect = lambda tid: dict(TRACK, id=tid)
    results = provider.lookup_many(["songhive:track:t1", "songhive:track:t2"])
    backend_mock.remote.get_tracks_by_ids.assert_called_once()
    assert sorted(results) == ["songhive:track:t1", "songhive:track:t2"]
    assert results["songhive:track:t1"][0].uri == "songhive:track:t1"
    assert results["songhive:track:t2"][0].uri == "songhive:track:t2"


def test_lookup_many_mixed(provider, backend_mock):
    backend_mock.remote.get_track.side_effect = lambda tid: dict(TRACK, id=tid)
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK]
    results = provider.lookup_many(
        ["songhive:track:t1", "songhive:playlist:p1"]
    )
    assert results["songhive:track:t1"][0].uri == "songhive:track:t1"
    assert results["songhive:playlist:p1"][0].uri == "songhive:track:track-1"


def test_lookup_many_missing_track(provider, backend_mock):
    backend_mock.remote.get_track.side_effect = KeyError("gone")
    results = provider.lookup_many(["songhive:track:t9"])
    assert results == {"songhive:track:t9": []}


def test_lookup_genre(provider, backend_mock):
    backend_mock.remote.get_genre_tracks.return_value = [TRACK]
    backend_mock.remote.get_genre_albums.return_value = [ALBUM]
    backend_mock.remote.get_album_tracks.return_value = [TRACK_2]
    tracks = provider.lookup("songhive:genre:rock")
    assert [t.uri for t in tracks] == [
        "songhive:track:track-1",
        "songhive:track:track-2",
    ]


def test_lookup_tag(provider, backend_mock):
    backend_mock.remote.get_tag_tracks.return_value = [TRACK]
    backend_mock.remote.get_tag_items.return_value = [
        {"type": "album", "id": "album-1"},
        {"type": "activity", "id": "act-1"},
        {"type": "track", "id": "track-9"},  # covered by tag tracks
    ]
    backend_mock.remote.get_album_tracks.return_value = [TRACK_2]
    tracks = provider.lookup("songhive:tag:live")
    assert [t.uri for t in tracks] == [
        "songhive:track:track-1",
        "songhive:track:track-2",
    ]
    backend_mock.remote.get_playlist_tracks.assert_not_called()
