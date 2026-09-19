from unittest import mock

import pytest
import requests

from mopidy_songhive.http import SonghiveHttpClient, SonghiveHttpError


@pytest.fixture
def client():
    return SonghiveHttpClient(
        "https://songhive.example.com/api/v1", token="tok"
    )


@pytest.fixture
def anon_client():
    return SonghiveHttpClient("https://songhive.example.com/api/v1")


def _response(status=200, json_data=None, headers=None, text=""):
    resp = mock.Mock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.text = text
    resp.json.side_effect = (
        (lambda: json_data) if json_data is not None else ValueError("no json")
    )
    return resp


def test_auth_header(client):
    assert client.session.headers["Authorization"] == "Bearer tok"
    assert client.authenticated


def test_anonymous_has_no_auth_header(anon_client):
    assert "Authorization" not in anon_client.session.headers
    assert not anon_client.authenticated


def test_url_building(client):
    assert client.url("/tracks/") == (
        "https://songhive.example.com/api/v1/tracks/"
    )
    assert client.url("tracks", {"q": "a b", "skip": None}) == (
        "https://songhive.example.com/api/v1/tracks?q=a+b"
    )


def test_get(client):
    client.session = mock.Mock()
    client.session.request.return_value = _response(json_data={"id": "1"})
    assert client.get("/tracks/1") == {"id": "1"}
    args, kwargs = client.session.request.call_args
    assert args[0] == "GET"
    assert args[1] == "https://songhive.example.com/api/v1/tracks/1"


def test_get_error_raises(client):
    client.session = mock.Mock()
    client.session.request.return_value = _response(
        status=404, json_data={"detail": "not found"}
    )
    with pytest.raises(SonghiveHttpError) as exc:
        client.get("/tracks/9")
    assert exc.value.status_code == 404
    assert "not found" in str(exc.value)


def test_get_retries_on_connection_error(client):
    client.session = mock.Mock()
    client.session.request.side_effect = [
        requests.ConnectionError("down"),
        _response(json_data={"ok": True}),
    ]
    assert client.get("/instance") == {"ok": True}
    assert client.session.request.call_count == 2


def test_get_exhausts_retries(client):
    client.session = mock.Mock()
    client.session.request.side_effect = requests.ConnectionError("down")
    with pytest.raises(SonghiveHttpError) as exc:
        client.get("/instance")
    assert exc.value.status_code == 0
    assert client.session.request.call_count == client.MAX_RETRIES


def test_get_all_paginates(client):
    page1 = _response(
        json_data=[{"id": i} for i in range(3)],
        headers={"X-Total-Count": "5"},
    )
    page2 = _response(json_data=[{"id": i} for i in range(3, 5)])
    client.session = mock.Mock()
    client.session.request.side_effect = [page1, page2]

    items = client.get_all("/tracks/", params={"limit": 3})
    assert len(items) == 5
    calls = client.session.request.call_args_list
    assert "offset=0" in calls[0][0][1]
    assert "offset=3" in calls[1][0][1]


def test_get_all_stops_on_short_page(client):
    client.session = mock.Mock()
    client.session.request.return_value = _response(
        json_data=[{"id": 1}, {"id": 2}]
    )
    items = client.get_all("/tracks/")
    assert len(items) == 2
    assert client.session.request.call_count == 1


def test_get_all_max_items(client):
    client.session = mock.Mock()
    client.session.request.return_value = _response(
        json_data=[{"id": i} for i in range(10)]
    )
    items = client.get_all("/tracks/", params={"limit": 10}, max_items=4)
    assert len(items) == 4


def test_delete(client):
    client.session = mock.Mock()
    client.session.request.return_value = _response(status=204)
    assert client.delete("/playlists/p1") is True
    client.session.request.return_value = _response(
        status=404, json_data={"detail": "gone"}
    )
    assert client.delete("/playlists/p1") is False


def test_post_sends_json(client):
    client.session = mock.Mock()
    client.session.request.return_value = _response(json_data={"id": "p1"})
    client.post("/playlists/", payload={"name": "x"})
    _, kwargs = client.session.request.call_args
    assert kwargs["json"] == {"name": "x"}
