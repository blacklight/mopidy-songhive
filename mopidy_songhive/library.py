import logging

from mopidy import backend, models

from . import uri as urilib
from .http import SonghiveHttpError

logger = logging.getLogger(__name__)

# Cap on the number of per-item requests issued while expanding tag folders.
_MAX_TAG_ITEM_FETCHES = 100


class SonghiveLibraryProvider(backend.LibraryProvider):

    root_directory = models.Ref.directory(
        uri=urilib.root_uri(), name="Songhive"
    )

    def browse(self, uri):
        kind, value = urilib.parse(uri)
        logger.debug("Songhive browse: %s (%s)", uri, kind)

        if kind == "root":
            return self._browse_root()

        if kind == "section":
            return self._browse_section(value)

        if kind == "item":
            item_kind, item_id = value
            return self._browse_item(item_kind, item_id)

        if kind == "url":
            resolved = self.backend.remote.resolve_url(value)
            if resolved is None:
                return []
            if resolved == uri:
                return []
            return self._refs_for_uri(resolved)

        return []

    def _browse_root(self):
        refs = [
            models.Ref.directory(
                uri=urilib.section_uri("libraries"), name="Libraries"
            ),
            models.Ref.directory(
                uri=urilib.section_uri("playlists"), name="Playlists"
            ),
            models.Ref.directory(
                uri=urilib.section_uri("artists"), name="Artists"
            ),
            models.Ref.directory(
                uri=urilib.section_uri("albums"), name="Albums"
            ),
        ]
        if self.backend.remote.authenticated:
            refs.append(
                models.Ref.directory(
                    uri=urilib.section_uri("favorites"), name="Favorites"
                )
            )
            refs.append(
                models.Ref.directory(
                    uri=urilib.section_uri("podcasts"), name="Podcasts"
                )
            )
        refs.extend(
            [
                models.Ref.directory(
                    uri=urilib.section_uri("genres"), name="Genres"
                ),
                models.Ref.directory(
                    uri=urilib.section_uri("tags"), name="Tags"
                ),
            ]
        )
        return refs

    def _browse_section(self, section):
        remote = self.backend.remote
        try:
            if section == "libraries":
                return [
                    remote.library_ref(lib) for lib in remote.get_libraries()
                ]
            if section == "playlists":
                return self.backend.playlists.as_list()
            if section == "artists":
                return [remote.artist_ref(a) for a in remote.get_artists()]
            if section == "albums":
                return [remote.album_ref(a) for a in remote.get_albums()]
            if section == "favorites":
                return [
                    remote.track_ref(t) for t in remote.get_favorite_tracks()
                ]
            if section == "genres":
                return [
                    remote.genre_ref(g["name"]) for g in remote.get_genres()
                ]
            if section == "tags":
                return [remote.tag_ref(t["name"]) for t in remote.get_tags()]
            if section == "podcasts":
                return [remote.podcast_ref(p) for p in remote.get_podcasts()]
        except SonghiveHttpError as exc:
            logger.info("Songhive browse of %s failed: %s", section, exc)
        return []

    def _browse_item(self, item_kind, item_id):
        remote = self.backend.remote
        try:
            if item_kind == "library":
                return [
                    remote.track_ref(t)
                    for t in remote.get_library_tracks(item_id)
                ]
            if item_kind == "playlist":
                return (
                    self.backend.playlists.get_items(
                        urilib.playlist_uri(item_id)
                    )
                    or []
                )
            if item_kind == "artist":
                return self._browse_artist(item_id)
            if item_kind == "album":
                return [
                    remote.track_ref(t)
                    for t in remote.get_album_tracks(item_id)
                ]
            if item_kind == "genre":
                return self._browse_genre(item_id)
            if item_kind == "tag":
                return self._browse_tag(item_id)
            if item_kind == "track":
                track = remote.get_track(item_id)
                return [remote.track_ref(track)] if track else []
            if item_kind == "podcast":
                return [
                    remote.podcast_episode_ref(e)
                    for e in remote.get_podcast_episodes(item_id)
                    if e.get("audio_url")
                ]
            if item_kind == "podcast_episode":
                episode = remote.get_podcast_episode(item_id)
                return [remote.podcast_episode_ref(episode)] if episode else []
        except SonghiveHttpError as exc:
            logger.info(
                "Songhive browse of %s:%s failed: %s", item_kind, item_id, exc
            )
        return []

    def _browse_artist(self, artist_id):
        """Albums of an artist, plus their tracks that are on no album."""
        remote = self.backend.remote
        artist = remote.get_artist(artist_id)
        refs = [remote.album_ref(a) for a in artist.get("albums") or []]
        refs.extend(
            remote.track_ref(t)
            for t in artist.get("tracks") or []
            if not t.get("album_id")
        )
        return refs

    def _browse_genre(self, name):
        remote = self.backend.remote
        refs = [remote.album_ref(a) for a in remote.get_genre_albums(name)]
        refs.extend(remote.track_ref(t) for t in remote.get_genre_tracks(name))
        return refs

    def _browse_tag(self, name):
        """Refs for every item carrying the tag, resolved per entity type."""
        remote = self.backend.remote
        refs = [remote.track_ref(t) for t in remote.get_tag_tracks(name)]

        fetchers = {
            "album": (remote.get_album, remote.album_ref),
            "artist": (remote.get_artist, remote.artist_ref),
            "playlist": (remote.get_playlist, remote.playlist_ref),
            "library": (remote.get_library, remote.library_ref),
        }
        for item_type, ids in self._tag_ids_by_type(remote, name).items():
            fetcher = fetchers.get(item_type)
            if fetcher is None:
                continue
            getter, ref_builder = fetcher
            fetched = remote.fetch_parallel(
                getter, ids[:_MAX_TAG_ITEM_FETCHES]
            )
            for item_id in ids[:_MAX_TAG_ITEM_FETCHES]:
                data = fetched.get(item_id)
                if data is not None:
                    refs.append(ref_builder(data))
        return refs

    def _refs_for_uri(self, songhive_uri):
        """Build a single ref pointing at a resolved songhive URI."""
        kind, value = urilib.parse(songhive_uri)
        remote = self.backend.remote
        if kind == "item":
            item_kind, item_id = value
            try:
                if item_kind == "track":
                    return [remote.track_ref(remote.get_track(item_id))]
                if item_kind == "album":
                    return [remote.album_ref(remote.get_album(item_id))]
                if item_kind == "artist":
                    return [remote.artist_ref(remote.get_artist(item_id))]
                if item_kind == "playlist":
                    return [remote.playlist_ref(remote.get_playlist(item_id))]
                if item_kind == "library":
                    return [remote.library_ref(remote.get_library(item_id))]
                if item_kind == "genre":
                    return [remote.genre_ref(item_id)]
                if item_kind == "tag":
                    return [remote.tag_ref(item_id)]
                if item_kind == "podcast":
                    return [remote.podcast_ref(remote.get_podcast(item_id))]
                if item_kind == "podcast_episode":
                    return [
                        remote.podcast_episode_ref(
                            remote.get_podcast_episode(item_id)
                        )
                    ]
            except SonghiveHttpError:
                return []
        elif kind == "remote":
            try:
                return [remote.remote_ref(remote.get_remote_object(value))]
            except SonghiveHttpError:
                return []
        elif kind == "section":
            name = value.capitalize()
            return [models.Ref.directory(uri=songhive_uri, name=name)]
        return []

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, uri):
        logger.debug("Songhive lookup: %s", uri)
        return self._lookup(uri, seen=set())

    def lookup_many(self, uris):
        """Resolve several URIs, fetching distinct tracks concurrently.

        Plain ``songhive:track:`` and ``songhive:podcast_episode:`` URIs
        dominate real-world call sites (queueing an album, a playlist, a
        podcast, or a whole library), so they go through one parallel
        fetch instead of sequential per-URI requests. Everything else
        falls back to the regular lookup path.
        """
        results = {}
        track_uris = {}
        episode_uris = {}
        other_uris = []
        for uri in uris:
            kind, value = urilib.parse(uri)
            if kind == "item" and value[0] == "track":
                track_uris[uri] = value[1]
            elif kind == "item" and value[0] == "podcast_episode":
                episode_uris[uri] = value[1]
            else:
                other_uris.append(uri)

        remote = self.backend.remote
        if track_uris:
            fetched = remote.get_tracks_by_ids(track_uris.values())
            for uri, track_id in track_uris.items():
                data = fetched.get(track_id)
                results[uri] = [remote.to_track(data)] if data else []

        if episode_uris:
            fetched = remote.get_podcast_episodes_by_ids(episode_uris.values())
            podcasts = remote.fetch_parallel(
                remote.get_podcast,
                [
                    e["podcast_id"]
                    for e in fetched.values()
                    if e.get("podcast_id")
                ],
            )
            for uri, episode_id in episode_uris.items():
                data = fetched.get(episode_id)
                if not data:
                    results[uri] = []
                    continue
                podcast = podcasts.get(data.get("podcast_id"))
                results[uri] = [remote.to_podcast_track(data, podcast)]

        for uri in other_uris:
            results[uri] = self._lookup(uri, seen=set())
        return results

    def _lookup(self, uri, seen):
        if uri in seen:
            return []
        seen.add(uri)

        kind, value = urilib.parse(uri)
        remote = self.backend.remote

        try:
            if kind == "item":
                item_kind, item_id = value
                if item_kind == "track":
                    return [remote.to_track(remote.get_track(item_id))]
                if item_kind == "album":
                    return [
                        remote.to_track(t)
                        for t in remote.get_album_tracks(item_id)
                    ]
                if item_kind == "artist":
                    return [
                        remote.to_track(t)
                        for t in remote.get_artist_tracks(item_id)
                    ]
                if item_kind == "playlist":
                    return [
                        remote.to_track(t)
                        for t in remote.get_playlist_tracks(item_id)
                    ]
                if item_kind == "library":
                    return [
                        remote.to_track(t)
                        for t in remote.get_library_tracks(item_id)
                    ]
                if item_kind == "genre":
                    return self._lookup_genre(item_id)
                if item_kind == "tag":
                    return self._lookup_tag(item_id)
                if item_kind == "podcast":
                    return self._lookup_podcast(item_id)
                if item_kind == "podcast_episode":
                    return [
                        self._episode_track(
                            remote.get_podcast_episode(item_id)
                        )
                    ]

            elif kind == "remote":
                obj = remote.get_remote_object(value)
                if obj.get("audio_url"):
                    return [remote.remote_object_track(obj)]
                return []

            elif kind == "url":
                resolved = remote.resolve_url(value)
                if resolved is None or resolved == uri:
                    return []
                return self._lookup(resolved, seen)

            elif kind == "section" and value == "favorites":
                return [
                    remote.to_track(t) for t in remote.get_favorite_tracks()
                ]

        except SonghiveHttpError as exc:
            logger.info("Songhive lookup of %s failed: %s", uri, exc)

        return []

    def _lookup_podcast(self, podcast_id):
        remote = self.backend.remote
        try:
            podcast = remote.get_podcast(podcast_id)
        except SonghiveHttpError:
            podcast = None
        return [
            remote.to_podcast_track(e, podcast)
            for e in remote.get_podcast_episodes(podcast_id)
            if e.get("audio_url")
        ]

    def _episode_track(self, episode):
        """Build a Track for an episode, attaching the show as album."""
        remote = self.backend.remote
        podcast = None
        podcast_id = episode.get("podcast_id")
        if podcast_id:
            try:
                podcast = remote.get_podcast(podcast_id)
            except SonghiveHttpError:
                podcast = None
        return remote.to_podcast_track(episode, podcast)

    def _lookup_genre(self, name):
        remote = self.backend.remote
        tracks = list(remote.get_genre_tracks(name))
        albums = remote.get_genre_albums(name)
        fetched = remote.fetch_parallel(
            remote.get_album_tracks, [a["id"] for a in albums]
        )
        for album in albums:
            tracks.extend(fetched.get(album["id"], []))
        return [remote.to_track(t) for t in tracks]

    def _lookup_tag(self, name):
        remote = self.backend.remote
        tracks = list(remote.get_tag_tracks(name))
        expanders = {
            "album": remote.get_album_tracks,
            "artist": remote.get_artist_tracks,
            "playlist": remote.get_playlist_tracks,
            "library": remote.get_library_tracks,
        }
        for item_type, ids in self._tag_ids_by_type(remote, name).items():
            expander = expanders.get(item_type)
            if expander is None:
                continue
            fetched = remote.fetch_parallel(
                expander, ids[:_MAX_TAG_ITEM_FETCHES]
            )
            for item_id in ids[:_MAX_TAG_ITEM_FETCHES]:
                tracks.extend(fetched.get(item_id, []))
        return [remote.to_track(t) for t in tracks]

    @staticmethod
    def _tag_ids_by_type(remote, name):
        """Group the ids of a tag's non-track items by their type."""
        by_type = {}
        for item in remote.get_tag_items(name):
            item_type = item.get("type")
            if item_type and item_type != "track" and item.get("id"):
                by_type.setdefault(item_type, []).append(item["id"])
        return by_type

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query=None, uris=None, exact=False):
        if uris and not any(u.startswith(urilib.ROOT) for u in uris):
            return None

        query = query or {}
        any_terms = list(query.get("any", []))
        track_terms = list(query.get("track_name", []))
        artist_terms = list(query.get("artist", [])) + list(
            query.get("albumartist", [])
        )
        album_terms = list(query.get("album", []))
        genre_terms = list(query.get("genre", []))
        date_terms = list(query.get("date", []))

        if not any(
            [any_terms, track_terms, artist_terms, album_terms, genre_terms]
        ):
            return models.SearchResult(uri=urilib.SEARCH)

        def matches(value, terms):
            if not terms:
                return True
            haystack = (value or "").lower()
            for term in terms:
                needle = term.lower()
                if exact:
                    if haystack == needle:
                        return True
                elif needle in haystack:
                    return True
            return False

        remote = self.backend.remote

        track_q = (
            track_terms or artist_terms or album_terms or any_terms or [None]
        )[0]
        try:
            raw_tracks = remote.get_tracks(
                {
                    "q": track_q,
                    "genre": genre_terms[0] if genre_terms else None,
                },
                max_items=300,
            )
        except SonghiveHttpError as exc:
            logger.info("Songhive track search failed: %s", exc)
            raw_tracks = []

        tracks = []
        for data in raw_tracks:
            track = remote.to_track(data)
            if not matches(track.name, track_terms):
                continue
            artist_name = (
                next(iter(track.artists)).name if track.artists else ""
            )
            if not matches(artist_name, artist_terms):
                continue
            if not matches(
                track.album.name if track.album else "", album_terms
            ):
                continue
            if not matches(track.genre, genre_terms):
                continue
            if date_terms and not matches(track.date, date_terms):
                continue
            if any_terms and not any(
                matches(field, any_terms)
                for field in (
                    track.name,
                    artist_name,
                    track.album.name if track.album else "",
                )
            ):
                continue
            tracks.append(track)

        album_q = (album_terms or artist_terms or any_terms or [None])[0]
        try:
            raw_albums = remote.get_albums(query=album_q)
        except SonghiveHttpError as exc:
            logger.info("Songhive album search failed: %s", exc)
            raw_albums = []

        albums = []
        for data in raw_albums:
            album = remote.to_album(data)
            if not matches(album.name, album_terms):
                continue
            album_artist = (
                next(iter(album.artists)).name if album.artists else ""
            )
            if not matches(album_artist, artist_terms):
                continue
            if any_terms and not any(
                matches(field, any_terms)
                for field in (album.name, album_artist)
            ):
                continue
            albums.append(album)

        artist_q = (artist_terms or any_terms or [None])[0]
        try:
            raw_artists = remote.get_artists(query=artist_q)
        except SonghiveHttpError as exc:
            logger.info("Songhive artist search failed: %s", exc)
            raw_artists = []

        artists = [
            remote.to_artist(a)
            for a in raw_artists
            if matches(a.get("name"), artist_terms + any_terms)
        ]

        # Federated track resources surfaced by the server's search.
        tracks.extend(self._remote_search_tracks(any_terms or track_terms))

        return models.SearchResult(
            uri=urilib.SEARCH,
            tracks=tracks,
            albums=albums,
            artists=artists,
        )

    def _remote_search_tracks(self, terms):
        """Fetch playable remote objects matching the search terms."""
        if not terms:
            return []
        remote = self.backend.remote
        try:
            sections = remote.search(terms[0], entities="remote")
        except SonghiveHttpError:
            return []
        ids = [
            item["id"]
            for item in sections.get("remote", [])
            if item.get("type") == "track" and item.get("id")
        ]
        fetched = remote.fetch_parallel(remote.get_remote_object, ids)
        return [
            remote.remote_object_track(obj)
            for obj in (fetched.get(item_id) for item_id in ids)
            if obj and obj.get("audio_url")
        ]

    # ------------------------------------------------------------------
    # Distinct fields / images
    # ------------------------------------------------------------------

    def get_distinct(self, field, query=None):
        remote = self.backend.remote
        try:
            if field in ("artist", "albumartist"):
                return {
                    a["name"] for a in remote.get_artists() if a.get("name")
                }
            if field == "album":
                return {
                    a["title"] for a in remote.get_albums() if a.get("title")
                }
            if field == "genre":
                return {g["name"] for g in remote.get_genres()}
        except SonghiveHttpError as exc:
            logger.info("Songhive get_distinct(%s) failed: %s", field, exc)
        return set()

    def get_images(self, uris):
        """Images for several URIs, fetched concurrently."""
        remote = self.backend.remote
        targets = {}
        for uri_ in uris:
            kind, value = urilib.parse(uri_)
            if kind == "item":
                targets[uri_] = value
            elif kind == "remote":
                targets[uri_] = ("remote", value)
        fetched = remote.fetch_parallel(
            lambda target: remote.get_image(*target),
            list(targets.values()),
        )
        results = {}
        for uri_ in uris:
            target = targets.get(uri_)
            results[uri_] = fetched.get(target, []) if target else []
        return results
