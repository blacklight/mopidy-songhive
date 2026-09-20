import sys
from unittest import mock

import pytest
from conftest import PODCAST_EPISODE, REMOTE_TRACK

from mopidy_songhive.playback import SonghivePlaybackProvider


@pytest.fixture
def provider(backend_mock):
    return SonghivePlaybackProvider(audio=mock.Mock(), backend=backend_mock)


def test_translate_track(provider, backend_mock):
    backend_mock.remote.stream_url.return_value = (
        "https://songhive.example.com/api/v1/stream/track-1"
    )
    result = provider.translate_uri("songhive:track:track-1")
    backend_mock.remote.stream_url.assert_called_once_with("track-1")
    assert result == "https://songhive.example.com/api/v1/stream/track-1"


def test_translate_remote(provider, backend_mock):
    backend_mock.remote.get_remote_object.return_value = REMOTE_TRACK
    result = provider.translate_uri("songhive:remote:remote-1")
    assert result == "https://other.example.com/api/v1/stream/99"


def test_translate_remote_relative_audio(provider, backend_mock):
    backend_mock.remote.get_remote_object.return_value = dict(
        REMOTE_TRACK, audio_url="/api/v1/stream/99"
    )
    result = provider.translate_uri("songhive:remote:remote-1")
    assert result == "https://other.example.com/api/v1/stream/99"


def test_translate_remote_without_audio(provider, backend_mock):
    backend_mock.remote.get_remote_object.return_value = dict(
        REMOTE_TRACK, audio_url=None
    )
    assert provider.translate_uri("songhive:remote:remote-1") is None


def test_translate_remote_http_error(provider, backend_mock):
    from mopidy_songhive.http import SonghiveHttpError

    backend_mock.remote.get_remote_object.side_effect = SonghiveHttpError(
        404, "gone"
    )
    assert provider.translate_uri("songhive:remote:remote-1") is None


def test_translate_podcast_episode(provider, backend_mock):
    backend_mock.remote.get_podcast_episode.return_value = PODCAST_EPISODE
    result = provider.translate_uri("songhive:podcast_episode:episode-1")
    backend_mock.remote.get_podcast_episode.assert_called_once_with(
        "episode-1"
    )
    assert result == "https://cdn.example.com/episodes/1.mp3"


def test_translate_podcast_episode_without_audio(provider, backend_mock):
    backend_mock.remote.get_podcast_episode.return_value = dict(
        PODCAST_EPISODE, audio_url=None
    )
    assert provider.translate_uri("songhive:podcast_episode:episode-1") is None


def test_translate_podcast_episode_http_error(provider, backend_mock):
    from mopidy_songhive.http import SonghiveHttpError

    backend_mock.remote.get_podcast_episode.side_effect = SonghiveHttpError(
        404, "gone"
    )
    assert provider.translate_uri("songhive:podcast_episode:episode-1") is None


def test_translate_embedded_url(provider, backend_mock):
    backend_mock.remote.resolve_url.return_value = "songhive:track:track-1"
    backend_mock.remote.stream_url.return_value = (
        "https://songhive.example.com/api/v1/stream/track-1"
    )
    result = provider.translate_uri(
        "songhive:https://songhive.example.com/tracks/track-1"
    )
    assert result == "https://songhive.example.com/api/v1/stream/track-1"


def test_translate_embedded_url_unresolvable(provider, backend_mock):
    backend_mock.remote.resolve_url.return_value = None
    result = provider.translate_uri(
        "songhive:https://elsewhere.example.com/x.mp3"
    )
    assert result is None


def test_translate_unknown_uri(provider):
    assert provider.translate_uri("file:///tmp/x.mp3") is None


def _fake_source(location):
    source = mock.Mock()
    source.find_property.side_effect = lambda name: (
        object() if name in ("extra-headers", "location") else None
    )
    source.get_property.side_effect = lambda name: (
        location if name == "location" else None
    )
    return source


@pytest.fixture
def fake_gst(monkeypatch):
    gst = mock.MagicMock()
    gi = mock.MagicMock()
    gi.repository.Gst = gst
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", gi.repository)
    return gst


def test_source_setup_injects_token(provider, backend_mock, fake_gst):
    source = _fake_source("https://songhive.example.com/api/v1/stream/track-1")
    provider.on_source_setup(source)

    headers = fake_gst.Structure.new_empty.return_value
    headers.set_value.assert_called_once_with(
        "Authorization", "Bearer test-token"
    )
    source.set_property.assert_called_once_with("extra-headers", headers)


def test_source_setup_skips_foreign_host(provider, backend_mock, fake_gst):
    source = _fake_source("https://other.example.com/api/v1/stream/99")
    provider.on_source_setup(source)
    source.set_property.assert_not_called()


def test_source_setup_skips_without_token(provider, backend_mock, fake_gst):
    backend_mock.remote.token = None
    source = _fake_source("https://songhive.example.com/api/v1/stream/track-1")
    provider.on_source_setup(source)
    source.set_property.assert_not_called()


def test_source_setup_without_headers_property(provider, fake_gst):
    source = mock.Mock()
    source.find_property.return_value = None
    provider.on_source_setup(source)
    source.set_property.assert_not_called()
