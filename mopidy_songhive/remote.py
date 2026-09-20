"""
Songhive API client.

Wraps the ``/api/v1`` REST endpoints and converts their payloads into
``mopidy.models`` objects. All calls are synchronous (``requests``), matching
how Mopidy backends are expected to work.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode, urljoin, urlparse

from mopidy import models

from . import uri
from .http import SonghiveHttpClient, SonghiveHttpError
from .utils import memoize

logger = logging.getLogger(__name__)

# Songhive ``remote_objects`` resource types that map to Mopidy refs.
REMOTE_RESOURCE_TYPES = ("track", "album", "artist", "playlist", "library")

# Item types returned by the ``/tags/{name}`` endpoint.
TAG_ITEM_TYPES = (
    "track",
    "album",
    "artist",
    "playlist",
    "library",
    "activity",
)

# Max concurrent requests issued when expanding several items at once.
_MAX_FETCH_WORKERS = 8


class SonghiveClient:
    """High level client for the Songhive REST API."""

    def __init__(self, config):
        self.config = config
        songhive = config.get("songhive", {})

        self.hostname = (songhive.get("hostname") or "").strip().rstrip("/")
        if self.hostname and "://" not in self.hostname:
            self.hostname = "https://" + self.hostname
        self.token = songhive.get("api_token") or None

        libraries = songhive.get("libraries") or ""
        self.library_allowlist = [
            name.strip() for name in libraries.split(",") if name.strip()
        ]

        self.album_format = songhive.get("album_format") or "{title}"
        self.transcode_format = songhive.get("transcode_format") or None
        bitrate = songhive.get("transcode_bitrate")
        self.transcode_bitrate = str(bitrate) if bitrate else None

        self.http = SonghiveHttpClient(
            f"{self.hostname}/api/v1",
            token=self.token,
            proxy=config.get("proxy"),
        )
        self.user = self._check_connection()

    @property
    def authenticated(self):
        return self.http.authenticated

    def _check_connection(self):
        """Validate connectivity/credentials; returns the user dict or None."""
        try:
            if self.token:
                user = self.http.get("/users/me")
                logger.info(
                    "Connected to Songhive at %s as %s",
                    self.hostname,
                    user.get("username"),
                )
                return user
            self.http.get("/instance")
            logger.info(
                "Connected to Songhive at %s anonymously "
                "(public content only)",
                self.hostname,
            )
        except SonghiveHttpError as exc:
            logger.error("Failed to connect to Songhive: %s", exc)
        return None

    def absolute_url(self, path_or_url):
        """Resolve a possibly-relative URL against the instance base URL."""
        if not path_or_url:
            return None
        return urljoin(self.hostname + "/", path_or_url)

    # ------------------------------------------------------------------
    # Model builders
    # ------------------------------------------------------------------

    def _artist_model(self, artist_summary=None, artist_id=None, name=None):
        if artist_summary:
            artist_id = artist_summary.get("id", artist_id)
            name = artist_summary.get("name", name)
        return models.Artist(
            uri=uri.artist_uri(artist_id) if artist_id else None,
            name=name,
        )

    def _album_model(self, data):
        """Build a mopidy Album from an AlbumResponse/AlbumSummary/track."""
        album_artist = data.get("artist") or {}
        artists = []
        if album_artist.get("id") or album_artist.get("name"):
            artists = [self._artist_model(album_artist)]

        release_year = data.get("release_year")
        return models.Album(
            uri=uri.album_uri(data["id"]),
            name=self.format_album(data),
            artists=artists,
            date=str(release_year) if release_year else None,
            musicbrainz_id=data.get("musicbrainz_id"),
        )

    def to_track(self, data):
        """Convert a TrackResponse/TrackSummary dict into a mopidy Track."""
        artist_data = data.get("artist") or {}
        artists = [
            self._artist_model(artist_data, artist_id=data.get("artist_id"))
        ]

        album = None
        album_data = data.get("album")
        album_id = data.get("album_id") or (album_data or {}).get("id")
        if album_data:
            album = self._album_model(album_data)
        elif album_id:
            album = models.Album(uri=uri.album_uri(album_id))

        genres = data.get("genres") or []
        genre = data.get("genre") or (genres[0] if genres else None)
        release_year = data.get("release_year")
        duration = data.get("duration")

        return models.Track(
            uri=uri.track_uri(data["id"]),
            name=data.get("title") or data.get("name"),
            artists=artists,
            album=album,
            track_no=data.get("track_number") or 0,
            disc_no=data.get("disc_number") or 0,
            genre=genre,
            date=str(release_year) if release_year else None,
            length=int(duration * 1000) if duration else None,
            comment=data.get("description"),
        )

    def to_album(self, data):
        return self._album_model(data)

    def to_artist(self, data):
        return models.Artist(
            uri=uri.artist_uri(data["id"]),
            name=data.get("name"),
            musicbrainz_id=data.get("musicbrainz_id"),
        )

    # ------------------------------------------------------------------
    # Ref builders
    # ------------------------------------------------------------------

    def track_ref(self, data):
        return models.Ref.track(
            uri=uri.track_uri(data["id"]),
            name=data.get("title") or data.get("name"),
        )

    def album_ref(self, data):
        return models.Ref.album(
            uri=uri.album_uri(data["id"]),
            name=self.format_album(data),
        )

    def artist_ref(self, data):
        return models.Ref.artist(
            uri=uri.artist_uri(data["id"]),
            name=data.get("name"),
        )

    def playlist_ref(self, data):
        return models.Ref.playlist(
            uri=uri.playlist_uri(data["id"]),
            name=data.get("name"),
        )

    def library_ref(self, data):
        return models.Ref.directory(
            uri=uri.library_uri(data["id"]),
            name=data.get("name"),
        )

    def genre_ref(self, name):
        return models.Ref.directory(uri=uri.genre_uri(name), name=str(name))

    def tag_ref(self, name):
        return models.Ref.directory(uri=uri.tag_uri(name), name=str(name))

    def podcast_ref(self, data):
        return models.Ref.directory(
            uri=uri.podcast_uri(data["id"]),
            name=data.get("title"),
        )

    def podcast_episode_ref(self, data):
        return models.Ref.track(
            uri=uri.podcast_episode_uri(data["id"]),
            name=data.get("title"),
        )

    def remote_ref(self, obj):
        """Build a ref for a cached remote object."""
        name = obj.get("name") or obj.get("domain")
        resource_type = obj.get("resource_type")
        if resource_type == "track" or obj.get("audio_url"):
            return models.Ref.track(uri=uri.remote_uri(obj["id"]), name=name)
        if resource_type == "album":
            return models.Ref.album(uri=uri.remote_uri(obj["id"]), name=name)
        if resource_type == "artist":
            return models.Ref.artist(uri=uri.remote_uri(obj["id"]), name=name)
        if resource_type == "playlist":
            return models.Ref.playlist(
                uri=uri.remote_uri(obj["id"]), name=name
            )
        return models.Ref.directory(uri=uri.remote_uri(obj["id"]), name=name)

    def format_album(self, data):
        """Apply the configured album name format to an album payload."""
        values = dict(data)
        values.setdefault("release_year", "")
        try:
            name = self.album_format.format(**values)
        except (KeyError, IndexError, ValueError):
            name = data.get("title") or data.get("name")
        return name

    def to_podcast_track(self, data, podcast=None):
        """Convert a PodcastEpisode payload into a mopidy Track.

        ``podcast`` is the optional parent-show payload; when present its
        title becomes the album and its author (or title) the artist.
        """
        artists = []
        album = None
        podcast = podcast or {}
        podcast_id = data.get("podcast_id") or podcast.get("id")
        if podcast_id:
            album = models.Album(
                uri=uri.podcast_uri(podcast_id),
                name=podcast.get("title"),
            )
        artist_name = podcast.get("author") or podcast.get("title")
        if artist_name:
            artists = [models.Artist(name=artist_name)]

        published_at = data.get("published_at")
        duration = data.get("duration_seconds")
        return models.Track(
            uri=uri.podcast_episode_uri(data["id"]),
            name=data.get("title"),
            artists=artists,
            album=album,
            track_no=data.get("episode_number") or 0,
            date=str(published_at)[:10] if published_at else None,
            length=int(duration * 1000) if duration else None,
            comment=data.get("description"),
            genre="Podcast",
        )

    def remote_object_track(self, obj):
        """Convert a remote object with an ``audio_url`` into a Track."""
        return models.Track(
            uri=uri.remote_uri(obj["id"]),
            name=obj.get("name") or obj.get("canonical_url"),
            artists=[
                models.Artist(
                    name=obj.get("actor_handle") or obj.get("domain")
                )
            ],
            comment=obj.get("summary"),
        )

    # ------------------------------------------------------------------
    # Libraries
    # ------------------------------------------------------------------

    @memoize(ttl=60)
    def get_libraries(self):
        """List libraries, honouring the configured name allowlist."""
        libraries = self.http.get_all("/libraries/")
        if self.library_allowlist:
            libraries = [
                lib
                for lib in libraries
                if lib.get("name") in self.library_allowlist
            ]
        return libraries

    @memoize(ttl=None)
    def get_library(self, library_id):
        return self.http.get(f"/libraries/{library_id}")

    @memoize(ttl=60)
    def get_library_tracks(self, library_id):
        return self.http.get_all(
            f"/libraries/{library_id}/tracks",
            params={
                "include": "artist,album",
                "sort_by": "album_title",
                "sort_dir": "asc",
            },
        )

    # ------------------------------------------------------------------
    # Artists / albums / tracks
    # ------------------------------------------------------------------

    @memoize(ttl=60)
    def get_artists(self, query=None):
        return self.http.get_all(
            "/artists/", params={"q": query, "sort_by": "name"}
        )

    @memoize(ttl=None)
    def get_artist(self, artist_id, include="albums,tracks"):
        return self.http.get(
            f"/artists/{artist_id}", params={"include": include}
        )

    @memoize(ttl=60)
    def get_albums(self, query=None, artist_id=None, genre=None):
        return self.http.get_all(
            "/albums/",
            params={
                "q": query,
                "artist_id": artist_id,
                "genre": genre,
                "include": "artist",
                "sort_by": "title",
            },
        )

    @memoize(ttl=None)
    def get_album(self, album_id, include="artist,tracks"):
        return self.http.get(
            f"/albums/{album_id}", params={"include": include}
        )

    @memoize(ttl=None)
    def get_track(self, track_id):
        return self.http.get(
            f"/tracks/{track_id}",
            params={"include": "artist,album,tags,genres"},
        )

    def get_tracks(self, params=None, max_items=None):
        params = {"include": "artist,album", **(params or {})}
        return self.http.get_all(
            "/tracks/", params=params, max_items=max_items
        )

    @memoize(ttl=60)
    def get_artist_tracks(self, artist_id):
        """All accessible tracks of an artist, sorted for sequential play."""
        tracks = self.get_tracks(
            {
                "artist_id": artist_id,
                "sort_by": "album_title",
                "sort_dir": "asc",
            }
        )
        return sorted(
            tracks,
            key=lambda t: (
                (t.get("album") or {}).get("title") or "",
                t.get("disc_number") or 0,
                t.get("track_number") or 0,
                t.get("title") or "",
            ),
        )

    @memoize(ttl=None)
    def get_album_tracks(self, album_id):
        """Tracks of an album, sorted by disc/track number."""
        album = self.get_album(album_id)
        tracks = album.get("tracks") or []
        return sorted(
            tracks,
            key=lambda t: (
                t.get("disc_number") or 0,
                t.get("track_number") or 0,
                t.get("title") or "",
            ),
        )

    # ------------------------------------------------------------------
    # Batch fetching
    # ------------------------------------------------------------------

    def fetch_parallel(self, getter, item_ids, max_workers=_MAX_FETCH_WORKERS):
        """Fetch several items concurrently through a single getter.

        Returns ``{item_id: result}`` for the ids that succeeded; failed
        fetches are logged and skipped. Ids are deduplicated, and entries
        already held by the getter's cache are served instantly.
        """
        unique_ids = list(dict.fromkeys(item_ids))
        results = {}
        if not unique_ids:
            return results
        workers = min(max_workers, len(unique_ids))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(getter, item_id): item_id for item_id in unique_ids
            }
            for future in as_completed(futures):
                item_id = futures[future]
                try:
                    results[item_id] = future.result()
                except Exception as exc:
                    logger.info(
                        "Songhive fetch of %s failed: %s", item_id, exc
                    )
        return results

    def get_tracks_by_ids(self, track_ids, max_workers=_MAX_FETCH_WORKERS):
        """Concurrently fetch track payloads for a list of track ids."""
        return self.fetch_parallel(
            self.get_track, track_ids, max_workers=max_workers
        )

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------

    @memoize(ttl=30)
    def get_favorite_tracks(self):
        """Favorite tracks of the authenticated user (empty when anonymous)."""
        if not self.authenticated:
            return []
        return self.get_tracks(
            {"favorited": "true", "sort_by": "created_at", "sort_dir": "desc"}
        )

    # ------------------------------------------------------------------
    # Podcasts
    # ------------------------------------------------------------------

    @memoize(ttl=60)
    def get_podcasts(self):
        """Podcasts the authenticated user follows (empty when anonymous)."""
        if not self.authenticated:
            return []
        return self.http.get_all(
            "/podcasts/",
            params={"sort_by": "latest", "sort_dir": "desc"},
        )

    @memoize(ttl=None)
    def get_podcast(self, podcast_id):
        return self.http.get(f"/podcasts/{podcast_id}")

    @memoize(ttl=60)
    def get_podcast_episodes(self, podcast_id):
        """Episodes of a podcast, newest first."""
        return self.http.get_all(
            f"/podcasts/{podcast_id}/episodes",
            params={"sort": "newest"},
        )

    @memoize(ttl=None)
    def get_podcast_episode(self, episode_id):
        return self.http.get(f"/podcasts/episodes/{episode_id}")

    def get_podcast_episodes_by_ids(
        self, episode_ids, max_workers=_MAX_FETCH_WORKERS
    ):
        """Concurrently fetch episode payloads for a list of episode ids."""
        return self.fetch_parallel(
            self.get_podcast_episode, episode_ids, max_workers=max_workers
        )

    # ------------------------------------------------------------------
    # Genres / tags
    # ------------------------------------------------------------------

    @memoize(ttl=60)
    def get_genres(self):
        return self.http.get_all("/genres/", params={"sort_by": "name"})

    @memoize(ttl=60)
    def get_genre_items(self, name):
        return self.http.get_all(f"/genres/{name}")

    @memoize(ttl=60)
    def get_genre_tracks(self, name):
        return self.get_tracks({"genre": name})

    @memoize(ttl=60)
    def get_genre_albums(self, name):
        return self.get_albums(genre=name)

    @memoize(ttl=60)
    def get_tags(self):
        return self.http.get_all("/tags/", params={"sort_by": "name"})

    @memoize(ttl=60)
    def get_tag_items(self, name):
        return self.http.get_all(f"/tags/{name}")

    @memoize(ttl=60)
    def get_tag_tracks(self, name):
        return self.get_tracks({"tag": name})

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, term, entities="tracks,albums,artists", limit=10):
        """Run the aggregate ``/search/`` endpoint; returns normalized items."""
        try:
            data = self.http.get(
                "/search/",
                params={
                    "q": term,
                    "entities": entities,
                    "limit": limit,
                    # Remote entities are excluded unless explicitly enabled.
                    "include_remote": "true",
                },
            )
        except SonghiveHttpError as exc:
            logger.info("Songhive search failed for %r: %s", term, exc)
            return {}
        return {
            section["entity"]: section.get("items", [])
            for section in data.get("sections", [])
        }

    # ------------------------------------------------------------------
    # Remote (federated) lookup
    # ------------------------------------------------------------------

    @memoize(ttl=300)
    def remote_lookup(self, value):
        """Resolve a handle/URL through ``/remote/lookup``."""
        return self.http.get("/remote/lookup", params={"input": value})

    @memoize(ttl=None)
    def get_remote_object(self, object_id):
        data = self.http.get(f"/remote/objects/{object_id}")
        return data.get("object") or data

    # ------------------------------------------------------------------
    # URL resolution
    # ------------------------------------------------------------------

    _SPA_RESOURCE_RE = re.compile(
        r"^/(tracks|albums|artists|playlists|libraries|podcasts)/([^/?#]+)/?$"
    )
    _SPA_TAG_RE = re.compile(r"^/(tags|genres)/([^/?#]+)/?$")
    _SPA_REMOTE_RE = re.compile(
        r"^/remote/(?:track|album|artist|playlist|library)/([^/?#]+)/?$"
    )
    _SPA_ACTIVITY_RE = re.compile(r"^/activities/@[^/]+/([^/?#]+)/?$")

    def _spa_route_to_uri(self, path):
        """Map an internal SPA route to a ``songhive:`` URI, or None."""
        match = self._SPA_RESOURCE_RE.match(path)
        if match:
            plural, item_id = match.groups()
            kind = {
                "tracks": "track",
                "albums": "album",
                "artists": "artist",
                "playlists": "playlist",
                "libraries": "library",
                "podcasts": "podcast",
            }[plural]
            return uri.item_uri(kind, item_id)

        match = self._SPA_TAG_RE.match(path)
        if match:
            section, name = match.groups()
            return uri.item_uri(section[:-1], name)

        match = self._SPA_REMOTE_RE.match(path) or self._SPA_ACTIVITY_RE.match(
            path
        )
        if match:
            return uri.remote_uri(match.group(1))

        if path == "/favorites":
            return uri.section_uri("favorites")

        if path == "/podcasts":
            return uri.section_uri("podcasts")

        return None

    def resolve_url(self, url):
        """Resolve a web URL to a ``songhive:`` URI, or None.

        Same-instance URLs are mapped to local entities straight from their
        path; anything else goes through ``/api/v1/remote/lookup``, which can
        dereference remote/federated objects and local permalinks alike.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None

        own = parsed.netloc.lower() == urlparse(self.hostname).netloc.lower()
        if own:
            resolved = self._spa_route_to_uri(parsed.path or "/")
            if resolved is not None:
                return resolved

        try:
            data = self.remote_lookup(url)
        except SonghiveHttpError as exc:
            logger.debug("Remote lookup of %r failed: %s", url, exc)
            return None

        kind = data.get("kind")
        if kind == "local":
            local_path = urlparse(data.get("url") or "").path
            return self._spa_route_to_uri(local_path)
        if kind in ("resource", "object"):
            obj = data.get("object") or {}
            if obj.get("id"):
                return uri.remote_uri(obj["id"])
        return None

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    @memoize(ttl=30)
    def get_playlists(self):
        return self.http.get_all("/playlists/", params={"sort_by": "name"})

    @memoize(ttl=30)
    def get_playlist(self, playlist_id):
        return self.http.get(f"/playlists/{playlist_id}")

    @memoize(ttl=30)
    def get_playlist_tracks(self, playlist_id):
        return self.http.get_all(
            f"/playlists/{playlist_id}/tracks",
            params={
                "include": "artist,album",
                "sort_by": "position",
                "sort_dir": "asc",
            },
        )

    def _invalidate_playlist(self, playlist_id):
        """Drop cached playlist entries after a mutation."""
        self.get_playlists.cache_invalidate(self)
        self.get_playlist.cache_invalidate(self, playlist_id)
        self.get_playlist_tracks.cache_invalidate(self, playlist_id)

    def create_playlist(self, name):
        data = self.http.post(
            "/playlists/",
            payload={"name": name},
            params={"visibility": "private"},
        )
        self.get_playlists.cache_invalidate(self)
        return data

    def delete_playlist(self, playlist_id):
        deleted = self.http.delete(f"/playlists/{playlist_id}")
        if deleted:
            self._invalidate_playlist(playlist_id)
        return deleted

    def rename_playlist(self, playlist_id, name):
        data = self.http.patch(
            f"/playlists/{playlist_id}", payload={"name": name}
        )
        self._invalidate_playlist(playlist_id)
        return data

    def add_playlist_tracks(
        self, playlist_id, track_ids, allow_duplicates=True
    ):
        if not track_ids:
            return
        try:
            self.http.post(
                f"/playlists/{playlist_id}/tracks",
                payload={
                    "track_ids": track_ids,
                    "allow_duplicates": allow_duplicates,
                },
            )
        except SonghiveHttpError as exc:
            if exc.status_code == 409 and allow_duplicates:
                raise
            if exc.status_code == 409:
                # Server found duplicates; ignore — the desired end state
                # already contains the tracks.
                return
            raise
        self.get_playlist_tracks.cache_invalidate(self, playlist_id)

    def remove_playlist_tracks(self, playlist_id, track_ids):
        if not track_ids:
            return
        self.http.post(
            f"/playlists/{playlist_id}/tracks/remove",
            payload={"track_ids": track_ids},
        )
        self.get_playlist_tracks.cache_invalidate(self, playlist_id)

    def reorder_playlist_tracks(self, playlist_id, track_ids, position=None):
        if not track_ids:
            return
        self.http.post(
            f"/playlists/{playlist_id}/tracks/reorder",
            payload={"track_ids": track_ids, "position": position},
        )
        self.get_playlist_tracks.cache_invalidate(self, playlist_id)

    # ------------------------------------------------------------------
    # Streaming / images
    # ------------------------------------------------------------------

    def stream_url(self, track_id):
        """Streaming URL for a local track (auth via ``on_source_setup``)."""
        params = {}
        if self.transcode_format:
            params["format"] = self.transcode_format
        if self.transcode_bitrate:
            # The server forwards the value to ffmpeg's ``-b:a``, which
            # interprets a bare number as bits/s — suffix kbps explicitly.
            params["bitrate"] = f"{self.transcode_bitrate}k"
        url = f"{self.hostname}/api/v1/stream/{track_id}"
        if params:
            url += "?" + urlencode(params)
        return url

    def is_own_url(self, url):
        """True when ``url`` points at the configured Songhive instance."""
        return bool(url) and url.startswith(f"{self.hostname}/")

    def get_image(self, kind, item_id):
        """Return a mopidy Image list for an entity, or an empty list."""
        path = {
            "track": f"/tracks/{item_id}",
            "album": f"/albums/{item_id}",
            "artist": f"/artists/{item_id}",
            "playlist": f"/playlists/{item_id}",
            "library": f"/libraries/{item_id}",
            "podcast": f"/podcasts/{item_id}",
            "podcast_episode": f"/podcasts/episodes/{item_id}",
            "remote": f"/remote/objects/{item_id}",
        }.get(kind)
        if path is None:
            return []

        try:
            data = self.http.get(path)
        except SonghiveHttpError:
            return []
        if kind == "remote":
            data = data.get("object") or {}

        url = (
            data.get("image_url")
            or data.get("cover_url")
            or data.get("avatar_url")
        )
        if not url and kind == "podcast_episode" and data.get("podcast_id"):
            # Episodes without their own artwork use the show's image.
            try:
                url = self.get_podcast(data["podcast_id"]).get("image_url")
            except SonghiveHttpError:
                url = None
        url = self.absolute_url(url)
        if not url:
            return []
        return [models.Image(uri=url)]
