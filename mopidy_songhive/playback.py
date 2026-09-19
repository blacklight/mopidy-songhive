import logging
from urllib.parse import urljoin

from mopidy import backend

from . import uri as urilib
from .http import SonghiveHttpError

logger = logging.getLogger(__name__)


class SonghivePlaybackProvider(backend.PlaybackProvider):

    def __init__(self, audio, backend):
        super().__init__(audio, backend)
        self._pending_stream_url = None

    def translate_uri(self, uri):
        client = self.backend.remote
        kind, value = urilib.parse(uri)
        logger.debug("Songhive translate_uri: %s (%s)", uri, kind)

        url = None
        if kind == "item" and value[0] == "track":
            url = client.stream_url(value[1])
        elif kind == "remote":
            url = self._remote_stream_url(value)
        elif kind == "url":
            resolved = client.resolve_url(value)
            if resolved is not None and resolved != uri:
                return self.translate_uri(resolved)

        self._pending_stream_url = url
        return url

    def _remote_stream_url(self, object_id):
        """Direct audio URL of a federated remote object."""
        try:
            obj = self.backend.remote.get_remote_object(object_id)
        except SonghiveHttpError as exc:
            logger.info(
                "Could not resolve remote object %s: %s", object_id, exc
            )
            return None
        audio_url = obj.get("audio_url")
        if not audio_url:
            logger.info("Remote object %s has no playable audio", object_id)
            return None
        if audio_url.startswith(("http://", "https://")):
            return audio_url
        # Relative audio URLs resolve against the remote object's page URL.
        return urljoin(obj.get("canonical_url", ""), audio_url)

    def on_source_setup(self, source):
        """Attach the API token to GStreamer sources fetching from our instance.

        ``translate_uri`` hands playbin a plain ``https://`` URL, so the only
        place a bearer token can be attached is the ``extra-headers``
        property of the HTTP source element. The header is only set when the
        source's location points at the configured Songhive instance, so the
        token can never leak to another host (e.g. remote audio or
        third-party URLs handled by other backends).
        """
        token = self.backend.remote.token
        if not token:
            return
        if source.find_property("extra-headers") is None:
            return

        location = self._source_location(source) or self._pending_stream_url
        if not location or not self.backend.remote.is_own_url(location):
            return

        try:
            from gi.repository import Gst  # type: ignore

            headers = Gst.Structure.new_empty("headers")
            headers.set_value("Authorization", f"Bearer {token}")
            source.set_property("extra-headers", headers)
        except Exception as exc:
            logger.debug("Could not set Songhive auth headers: %s", exc)

    @staticmethod
    def _source_location(source):
        """Best-effort read of the URL a GStreamer source will fetch."""
        for prop in ("location", "uri"):
            try:
                if source.find_property(prop) is None:
                    continue
                value = source.get_property(prop)
            except Exception:
                continue
            if value:
                return value
        return None
