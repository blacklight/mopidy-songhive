import logging
import os
from pathlib import Path

from mopidy import config, ext

__version__ = "0.1.5"

logger = logging.getLogger(__name__)


class Extension(ext.Extension):

    dist_name = "Mopidy-Songhive"
    ext_name = "songhive"
    version = __version__

    def get_default_config(self):
        conf_file = Path(os.path.dirname(__file__), "ext.conf")
        return config.read(conf_file)

    def get_config_schema(self):
        schema = super().get_config_schema()
        schema["hostname"] = config.String()
        schema["api_token"] = config.Secret(optional=True)
        schema["libraries"] = config.String(optional=True)
        schema["album_format"] = config.String(optional=True)
        schema["playlist_format"] = config.String(optional=True)
        schema["transcode_format"] = config.String(optional=True)
        schema["transcode_bitrate"] = config.Integer(optional=True)
        return schema

    def setup(self, registry):
        from .backend import SonghiveBackend

        registry.add("backend", SonghiveBackend)
