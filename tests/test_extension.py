import mopidy_songhive
from mopidy_songhive import Extension


def test_get_default_config():
    ext = Extension()
    config = ext.get_default_config()
    assert "[songhive]" in config
    assert "enabled = true" in config


def test_get_config_schema():
    ext = Extension()
    schema = ext.get_config_schema()
    for key in (
        "hostname",
        "api_token",
        "libraries",
        "album_format",
        "transcode_format",
        "transcode_bitrate",
    ):
        assert key in schema


def test_extension_metadata():
    assert Extension.dist_name == "Mopidy-Songhive"
    assert Extension.ext_name == "songhive"
    assert Extension.version == mopidy_songhive.__version__
