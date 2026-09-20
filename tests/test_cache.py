from mopidy_songhive.cache import MetadataCache


def test_memory_only_roundtrip():
    cache = MetadataCache()
    assert cache.get("track", "t1") is None
    cache.set("track", "t1", {"id": "t1", "title": "Song"})
    assert cache.get("track", "t1")["title"] == "Song"


def test_disk_roundtrip(tmp_path):
    cache = MetadataCache(tmp_path)
    cache.set("track", "t1", {"id": "t1", "title": "Song"})
    assert (tmp_path / "metadata.db").exists()

    # A fresh instance over the same dir reads the stored payload.
    assert MetadataCache(tmp_path).get("track", "t1")["title"] == "Song"


def test_set_many(tmp_path):
    cache = MetadataCache(tmp_path)
    cache.set_many(
        "track",
        [{"id": "t1"}, {"id": "t2"}, {"no_id": True}, "not-a-dict"],
    )
    assert cache.get("track", "t1") == {"id": "t1"}
    assert MetadataCache(tmp_path).get("track", "t2") == {"id": "t2"}


def test_kinds_are_separate(tmp_path):
    cache = MetadataCache(tmp_path)
    cache.set("track", "1", {"what": "track"})
    cache.set("podcast_episode", "1", {"what": "episode"})
    assert cache.get("track", "1")["what"] == "track"
    assert cache.get("podcast_episode", "1")["what"] == "episode"


def test_invalidate(tmp_path):
    cache = MetadataCache(tmp_path)
    cache.set("track", "t1", {"id": "t1"})
    cache.invalidate("track", "t1")
    assert cache.get("track", "t1") is None
    assert MetadataCache(tmp_path).get("track", "t1") is None


def test_unwritable_dir_is_memory_only(tmp_path):
    missing = tmp_path / "missing" / "subdir"
    cache = MetadataCache(missing)
    cache.set("track", "t1", {"id": "t1"})
    assert cache.get("track", "t1") == {"id": "t1"}
    # Nothing was persisted, so a new instance sees nothing.
    assert MetadataCache(missing).get("track", "t1") is None
