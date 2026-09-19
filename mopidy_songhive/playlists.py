import logging
import operator
from collections import Counter

from mopidy import backend, models

from . import uri as urilib
from .http import SonghiveHttpError

logger = logging.getLogger(__name__)


def _track_id(track):
    """Extract the Songhive track id from a mopidy track's URI."""
    kind, value = urilib.parse(track.uri)
    if kind == "item" and value[0] == "track":
        return value[1]
    return None


def _dedupe(ids):
    """Return ``ids`` with duplicates removed, order preserved."""
    return list(dict.fromkeys(ids))


class SonghivePlaylistsProvider(backend.PlaylistsProvider):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.refresh()

    @property
    def _remote(self):
        return self.backend.remote

    def _writable(self, what):
        """Guard for operations that need an authenticated session."""
        if not self._remote.authenticated:
            logger.warning(
                "Cannot %s: no Songhive API token configured "
                "(anonymous access is read-only)",
                what,
            )
            return False
        return True

    def as_list(self):
        """All playlists visible to the caller, sorted by name."""
        try:
            playlists = self._remote.get_playlists()
        except SonghiveHttpError as exc:
            logger.info("Could not list Songhive playlists: %s", exc)
            return []
        refs = [
            models.Ref.playlist(
                uri=urilib.playlist_uri(p["id"]),
                name=p.get("name") or "",
            )
            for p in playlists
        ]
        return sorted(refs, key=operator.attrgetter("name"))

    def get_items(self, uri):
        kind, value = urilib.parse(uri)
        if kind != "item" or value[0] != "playlist":
            return None
        try:
            tracks = self._remote.get_playlist_tracks(value[1])
        except SonghiveHttpError as exc:
            logger.info("Could not load playlist %s: %s", uri, exc)
            return None
        return [self._remote.track_ref(t) for t in tracks]

    def lookup(self, uri):
        kind, value = urilib.parse(uri)
        if kind != "item" or value[0] != "playlist":
            return None
        playlist_id = value[1]
        try:
            data = self._remote.get_playlist(playlist_id)
            tracks = [
                self._remote.to_track(t)
                for t in self._remote.get_playlist_tracks(playlist_id)
            ]
        except SonghiveHttpError as exc:
            logger.info("Could not look up playlist %s: %s", uri, exc)
            return None
        return models.Playlist(
            uri=uri,
            name=data.get("name"),
            tracks=tracks,
        )

    def refresh(self):
        backend.BackendListener.send("playlists_loaded")
        return []

    def create(self, name):
        if not self._writable("create playlists"):
            return None
        try:
            data = self._remote.create_playlist(name)
        except SonghiveHttpError as exc:
            logger.info("Could not create playlist %r: %s", name, exc)
            return None
        return models.Playlist(
            uri=urilib.playlist_uri(data["id"]),
            name=data.get("name") or name,
            tracks=[],
        )

    def delete(self, uri):
        if not self._writable("delete playlists"):
            return False
        kind, value = urilib.parse(uri)
        if kind != "item" or value[0] != "playlist":
            return False
        return self._remote.delete_playlist(value[1])

    def save(self, playlist):
        """Sync the full playlist to the server.

        Songhive applies playlist edits as add/remove/reorder operations, so
        the desired state is reconciled against the current server state:

        1. track ids absent from the desired list are removed (all copies),
        2. missing copies are appended (duplicates allowed),
        3. the resulting order is fixed with per-track move operations.
        """
        if not self._writable("modify playlists"):
            return None

        kind, value = urilib.parse(playlist.uri)
        if kind != "item" or value[0] != "playlist":
            logger.warning("Cannot save playlist with uri %s", playlist.uri)
            return None
        playlist_id = value[1]

        desired_ids = [
            tid for tid in (_track_id(t) for t in playlist.tracks) if tid
        ]

        try:
            # The diff must run on the freshest server state, not the
            # (possibly stale) cached track list.
            self._remote.get_playlist_tracks.cache_invalidate(
                self._remote, playlist_id
            )
            current_ids = [
                t["id"] for t in self._remote.get_playlist_tracks(playlist_id)
            ]

            removed = [
                tid
                for tid, count in Counter(current_ids).items()
                if count > Counter(desired_ids)[tid]
            ]
            if removed:
                self._remote.remove_playlist_tracks(playlist_id, removed)
                current_ids = [
                    tid for tid in current_ids if tid not in removed
                ]

            missing_counter = Counter(desired_ids) - Counter(current_ids)
            missing = []
            seen = Counter()
            for tid in desired_ids:
                if seen[tid] < missing_counter[tid]:
                    missing.append(tid)
                    seen[tid] += 1
            if missing:
                self._remote.add_playlist_tracks(
                    playlist_id, missing, allow_duplicates=True
                )

            self._sync_order(playlist_id, current_ids + missing, desired_ids)

            if playlist.name:
                try:
                    remote_data = self._remote.get_playlist(playlist_id)
                    if remote_data.get("name") != playlist.name:
                        self._remote.rename_playlist(
                            playlist_id, playlist.name
                        )
                except SonghiveHttpError:
                    pass
        except SonghiveHttpError as exc:
            logger.info("Could not save playlist %s: %s", playlist.uri, exc)
            return None

        return playlist

    def _sync_order(self, playlist_id, current_ids, desired_ids):
        """Move tracks so the playlist matches ``desired_ids``.

        Songhive's reorder endpoint moves *all occurrences* of the listed
        track ids to a position, so ordering is reconciled on deduplicated
        id sequences — duplicate entries cannot be positioned individually
        and keep their relative order.
        """
        current = _dedupe(current_ids)
        wanted = _dedupe(desired_ids)
        if current == wanted:
            return

        for position, track_id in enumerate(wanted, start=1):
            index = position - 1
            if index < len(current) and current[index] == track_id:
                continue
            self._remote.reorder_playlist_tracks(
                playlist_id, [track_id], position=position
            )
            current = [tid for tid in current if tid != track_id]
            current.insert(index, track_id)
