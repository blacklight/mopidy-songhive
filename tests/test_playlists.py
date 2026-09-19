import mopidy
import pytest
from conftest import PLAYLIST, TRACK, TRACK_2

from mopidy_songhive.playlists import SonghivePlaylistsProvider


def track_model(track_id):
    return mopidy.models.Track(uri=f"songhive:track:{track_id}", name=track_id)


@pytest.fixture
def provider(backend_mock):
    return SonghivePlaylistsProvider(backend=backend_mock)


def test_as_list(provider, backend_mock):
    backend_mock.remote.get_playlists.return_value = [
        dict(PLAYLIST, name="Zulu"),
        dict(PLAYLIST, id="playlist-2", name="Alpha"),
    ]
    refs = provider.as_list()
    assert [r.name for r in refs] == ["Alpha", "Zulu"]
    assert refs[0].uri == "songhive:playlist:playlist-2"
    assert all(r.type == mopidy.models.Ref.PLAYLIST for r in refs)


def test_get_items(provider, backend_mock):
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK, TRACK_2]
    refs = provider.get_items("songhive:playlist:playlist-1")
    assert [r.uri for r in refs] == [
        "songhive:track:track-1",
        "songhive:track:track-2",
    ]


def test_get_items_wrong_uri(provider):
    assert provider.get_items("songhive:track:x") is None


def test_lookup(provider, backend_mock):
    backend_mock.remote.get_playlist.return_value = PLAYLIST
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK]
    playlist = provider.lookup("songhive:playlist:playlist-1")
    assert playlist.name == "My Playlist"
    assert [t.uri for t in playlist.tracks] == ["songhive:track:track-1"]


def test_create(provider, backend_mock):
    backend_mock.remote.create_playlist.return_value = dict(
        PLAYLIST, id="playlist-9", name="Fresh"
    )
    playlist = provider.create("Fresh")
    backend_mock.remote.create_playlist.assert_called_once_with("Fresh")
    assert playlist.uri == "songhive:playlist:playlist-9"
    assert playlist.name == "Fresh"
    assert list(playlist.tracks) == []


def test_create_anonymous(provider, backend_mock):
    backend_mock.remote.authenticated = False
    assert provider.create("Nope") is None
    backend_mock.remote.create_playlist.assert_not_called()


def test_delete(provider, backend_mock):
    backend_mock.remote.delete_playlist.return_value = True
    assert provider.delete("songhive:playlist:playlist-1") is True
    backend_mock.remote.delete_playlist.assert_called_once_with("playlist-1")


def test_delete_anonymous(provider, backend_mock):
    backend_mock.remote.authenticated = False
    assert provider.delete("songhive:playlist:playlist-1") is False
    backend_mock.remote.delete_playlist.assert_not_called()


def test_save_adds_tracks(provider, backend_mock):
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK]
    backend_mock.remote.get_playlist.return_value = PLAYLIST
    playlist = mopidy.models.Playlist(
        uri="songhive:playlist:playlist-1",
        name="My Playlist",
        tracks=[track_model("track-1"), track_model("track-9")],
    )
    result = provider.save(playlist)
    assert result is playlist
    backend_mock.remote.add_playlist_tracks.assert_called_once_with(
        "playlist-1", ["track-9"], allow_duplicates=True
    )
    backend_mock.remote.remove_playlist_tracks.assert_not_called()


def test_save_removes_tracks(provider, backend_mock):
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK, TRACK_2]
    backend_mock.remote.get_playlist.return_value = PLAYLIST
    playlist = mopidy.models.Playlist(
        uri="songhive:playlist:playlist-1",
        name="My Playlist",
        tracks=[track_model("track-1")],
    )
    provider.save(playlist)
    backend_mock.remote.remove_playlist_tracks.assert_called_once_with(
        "playlist-1", ["track-2"]
    )
    backend_mock.remote.add_playlist_tracks.assert_not_called()


def test_save_reorders(provider, backend_mock):
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK, TRACK_2]
    backend_mock.remote.get_playlist.return_value = PLAYLIST
    playlist = mopidy.models.Playlist(
        uri="songhive:playlist:playlist-1",
        name="My Playlist",
        tracks=[track_model("track-2"), track_model("track-1")],
    )
    provider.save(playlist)
    backend_mock.remote.reorder_playlist_tracks.assert_called_once_with(
        "playlist-1", ["track-2"], position=1
    )
    backend_mock.remote.add_playlist_tracks.assert_not_called()
    backend_mock.remote.remove_playlist_tracks.assert_not_called()


def test_save_no_reorder_when_already_ordered(provider, backend_mock):
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK, TRACK_2]
    backend_mock.remote.get_playlist.return_value = PLAYLIST
    playlist = mopidy.models.Playlist(
        uri="songhive:playlist:playlist-1",
        name="My Playlist",
        tracks=[track_model("track-1"), track_model("track-2")],
    )
    provider.save(playlist)
    backend_mock.remote.reorder_playlist_tracks.assert_not_called()


def test_save_renames(provider, backend_mock):
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK]
    backend_mock.remote.get_playlist.return_value = PLAYLIST
    playlist = mopidy.models.Playlist(
        uri="songhive:playlist:playlist-1",
        name="Renamed",
        tracks=[track_model("track-1")],
    )
    provider.save(playlist)
    backend_mock.remote.rename_playlist.assert_called_once_with(
        "playlist-1", "Renamed"
    )


def test_save_anonymous(provider, backend_mock):
    backend_mock.remote.authenticated = False
    playlist = mopidy.models.Playlist(
        uri="songhive:playlist:playlist-1",
        name="My Playlist",
        tracks=[],
    )
    assert provider.save(playlist) is None
    backend_mock.remote.get_playlist_tracks.assert_not_called()


def test_save_add_remove_reorder_combined(provider, backend_mock):
    # current: [t1, t2], desired: [t2, t3]
    backend_mock.remote.get_playlist_tracks.return_value = [TRACK, TRACK_2]
    backend_mock.remote.get_playlist.return_value = PLAYLIST
    playlist = mopidy.models.Playlist(
        uri="songhive:playlist:playlist-1",
        name="My Playlist",
        tracks=[track_model("track-2"), track_model("track-3")],
    )
    provider.save(playlist)
    backend_mock.remote.remove_playlist_tracks.assert_called_once_with(
        "playlist-1", ["track-1"]
    )
    backend_mock.remote.add_playlist_tracks.assert_called_once_with(
        "playlist-1", ["track-3"], allow_duplicates=True
    )
    # after sync: [t2, t3] — already ordered, no reorder needed
    backend_mock.remote.reorder_playlist_tracks.assert_not_called()
