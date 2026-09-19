from mopidy_songhive import uri


def test_root():
    assert uri.parse("songhive:") == ("root", None)


def test_sections():
    assert uri.parse("songhive:libraries") == ("section", "libraries")
    assert uri.parse("songhive:favorites") == ("section", "favorites")
    assert uri.parse("songhive:tags") == ("section", "tags")


def test_items():
    assert uri.parse("songhive:track:abc123") == (
        "item",
        ("track", "abc123"),
    )
    assert uri.parse("songhive:album:42") == ("item", ("album", "42"))
    assert uri.parse("songhive:playlist:p1") == (
        "item",
        ("playlist", "p1"),
    )


def test_genre_and_tag_names():
    assert uri.parse("songhive:genre:drum%20%26%20bass") == (
        "item",
        ("genre", "drum & bass"),
    )
    assert uri.parse("songhive:tag:my_tag") == ("item", ("tag", "my_tag"))


def test_remote():
    assert uri.parse("songhive:remote:obj-9") == ("remote", "obj-9")


def test_search_pseudo_uri():
    assert uri.parse("songhive:search") == ("search", None)


def test_embedded_url():
    value = "https://music.example.com/tracks/abc123"
    assert uri.parse(f"songhive:{value}") == ("url", value)


def test_unknown():
    assert uri.parse("file:///tmp/x.mp3") == ("unknown", None)
    assert uri.parse("songhive:bogus") == ("unknown", None)
    assert uri.parse("songhive:bogus:1") == ("unknown", None)
    assert uri.parse(None) == ("unknown", None)


def test_builders():
    assert uri.track_uri("t1") == "songhive:track:t1"
    assert uri.album_uri("a1") == "songhive:album:a1"
    assert uri.artist_uri("r1") == "songhive:artist:r1"
    assert uri.playlist_uri("p1") == "songhive:playlist:p1"
    assert uri.library_uri("l1") == "songhive:library:l1"
    assert uri.genre_uri("drum & bass") == "songhive:genre:drum%20%26%20bass"
    assert uri.tag_uri("x") == "songhive:tag:x"
    assert uri.remote_uri("o1") == "songhive:remote:o1"
    assert uri.section_uri("artists") == "songhive:artists"


def test_roundtrip_quoted_names():
    name = "drum & bass/ambient"
    kind, value = uri.parse(uri.genre_uri(name))
    assert kind == "item"
    assert value == ("genre", name)
