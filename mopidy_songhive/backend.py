import logging

import pykka
from mopidy import backend
from mopidy.types import UriScheme

from mopidy_songhive.library import SonghiveLibraryProvider
from mopidy_songhive.playback import SonghivePlaybackProvider
from mopidy_songhive.playlists import SonghivePlaylistsProvider
from mopidy_songhive.remote import SonghiveClient

logger = logging.getLogger(__name__)


class SonghiveBackend(pykka.ThreadingActor, backend.Backend):
    uri_schemes = [UriScheme("songhive")]

    def __init__(self, config, audio):
        super().__init__()

        self.remote = SonghiveClient(config)
        self.library = SonghiveLibraryProvider(backend=self)
        self.playback = SonghivePlaybackProvider(audio=audio, backend=self)
        self.playlists = SonghivePlaylistsProvider(backend=self)
