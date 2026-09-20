"""
Helpers for building and parsing ``songhive:`` URIs.

Scheme layout::

    songhive:                      browse root
    songhive:libraries             all libraries (folders)
    songhive:library:<id>          tracks of a library
    songhive:playlists             all playlists (folders)
    songhive:playlist:<id>         tracks of a playlist
    songhive:artists               all artists
    songhive:artist:<id>           albums and tracks of an artist
    songhive:albums                all albums
    songhive:album:<id>            tracks of an album
    songhive:favorites             the user's favorite tracks
    songhive:genres                all genres (folders)
    songhive:genre:<name>          items of a genre
    songhive:tags                  all tags (folders)
    songhive:tag:<name>            items of a tag
    songhive:track:<id>            a single track
    songhive:podcasts              all followed podcasts (folders)
    songhive:podcast:<id>          episodes of a podcast
    songhive:podcast_episode:<id>  a single podcast episode
    songhive:remote:<object_id>    a cached remote (federated) object
    songhive:search                pseudo URI identifying search results
    songhive:<url>                 an embedded URL (see below)

Any ``http(s)://`` URL can be embedded directly after the scheme, e.g.
``songhive:https://music.example.com/tracks/abc123``. URLs pointing at the
configured instance are mapped to the matching local entity; other URLs are
resolved through the instance's ``/api/v1/remote/lookup`` endpoint.
"""

from urllib.parse import quote, unquote

from mopidy.types import Uri

SCHEME = "songhive"
ROOT = f"{SCHEME}:"
SEARCH = Uri(f"{SCHEME}:search")

SECTIONS = (
    "libraries",
    "playlists",
    "artists",
    "albums",
    "favorites",
    "genres",
    "tags",
    "podcasts",
)

ITEM_KINDS = (
    "library",
    "playlist",
    "artist",
    "album",
    "track",
    "genre",
    "tag",
    "podcast",
    "podcast_episode",
    "remote",
)


def quote_id(value) -> str:
    """Quote an identifier for embedding inside a ``songhive:`` URI."""
    return quote(str(value), safe="")


def unquote_id(value: str) -> str:
    """Unquote an identifier extracted from a ``songhive:`` URI."""
    return unquote(value)


def root_uri() -> Uri:
    return Uri(ROOT)


def section_uri(section: str) -> Uri:
    return Uri(f"{SCHEME}:{section}")


def item_uri(kind: str, item_id) -> Uri:
    return Uri(f"{SCHEME}:{kind}:{quote_id(item_id)}")


def track_uri(track_id) -> Uri:
    return item_uri("track", track_id)


def album_uri(album_id) -> Uri:
    return item_uri("album", album_id)


def artist_uri(artist_id) -> Uri:
    return item_uri("artist", artist_id)


def playlist_uri(playlist_id) -> Uri:
    return item_uri("playlist", playlist_id)


def library_uri(library_id) -> Uri:
    return item_uri("library", library_id)


def genre_uri(name) -> Uri:
    return item_uri("genre", name)


def tag_uri(name) -> Uri:
    return item_uri("tag", name)


def podcast_uri(podcast_id) -> Uri:
    return item_uri("podcast", podcast_id)


def podcast_episode_uri(episode_id) -> Uri:
    return item_uri("podcast_episode", episode_id)


def remote_uri(object_id) -> Uri:
    return item_uri("remote", object_id)


def parse(uri):
    """Parse a ``songhive:`` URI.

    Returns ``(kind, value)`` where ``kind`` is one of:

    * ``"root"``    — the ``songhive:`` root; value is ``None``
    * ``"section"`` — a plural section, value is the section name
    * ``"item"``    — ``kind:id``; value is ``(item_kind, id)``
    * ``"remote"``  — a remote object; value is the object id
    * ``"url"``     — an embedded http(s) URL; value is the URL
    * ``"search"``  — the search pseudo URI; value is ``None``
    * ``"unknown"`` — anything else; value is ``None``
    """
    if not isinstance(uri, str) or not uri.startswith(ROOT):
        return ("unknown", None)

    rest = uri[len(ROOT) :]
    if not rest:
        return ("root", None)

    if rest == "search":
        return ("search", None)

    if rest.startswith(("http://", "https://")):
        return ("url", rest)

    kind, sep, value = rest.partition(":")
    if not sep:
        if kind in SECTIONS:
            return ("section", kind)
        return ("unknown", None)

    if kind == "remote":
        return ("remote", unquote_id(value))

    if kind in ITEM_KINDS:
        return ("item", (kind, unquote_id(value)))

    return ("unknown", None)
