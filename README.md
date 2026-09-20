# Mopidy-Songhive

[Mopidy](https://mopidy.com) extension for playing music from a
[Songhive](https://git.fabiomanganiello.com/songhive) instance.

## Features

- Browse libraries, playlists, artists, albums, genres and tags
- Followed podcasts exposed in their own folder, one sub-folder per show;
  episodes stream straight from the source enclosure URL
- Favorite tracks exposed as a browsable folder
- Full text search across tracks, albums and artists (plus cached
  federated objects)
- Playlist editing: create, delete, rename, add/remove/reorder tracks
- Streams through Songhive's `/api/v1/stream/{track_id}` endpoint,
  including optional server-side transcoding
- Federated content: remote objects resolve and play through the
  instance's remote lookup
- Direct URL lookup — paste any Songhive or federated URL prefixed with
  `songhive:` (e.g. `songhive:https://music.example.com/tracks/abc123`)
- Track metadata is cached on disk and seeded straight from collection
  listings, so queueing a browsed album, playlist or podcast needs no
  extra requests; metadata is re-fetched when a track plays to stay
  fresh, and the remaining lookups run concurrently

## Requirements

- Mopidy >= 4.0
- Python >= 3.9

## Installation

Install by running:

```sh
pip install mopidy-songhive
```

Or install the development version:

```sh
pip install -e .
```

## Configuration

Add the extension to your `mopidy.conf`:

```ini
[songhive]
enabled = true
hostname = https://music.example.com
api_token = <your api token>
```

`api_token` is optional: without it the extension runs anonymously and
only sees public content; playlists and favorites become read-only.
Create a token on the Songhive web interface under *Settings → API
tokens*. Tokens are sent as `Authorization: Bearer` headers and, for
audio streaming, injected into GStreamer's HTTP source — they are only
ever sent to the configured `hostname`.

Additional options:

```ini
# Comma-separated allowlist of library names to show (default: all)
libraries = Music, Audiobooks

# Format for displaying album names (default: {title})
album_format = {title} ({release_year})

# Optional server-side transcoding for streams
transcode_format = opus     # mp3|ogg|flac|aac|opus
transcode_bitrate = 128     # kbps
```

## URI scheme

`songhive:track:123`, `songhive:album:123`, `songhive:artist:123`,
`songhive:playlist:123`, `songhive:library:123`,
`songhive:genre:rock`, `songhive:tag:favorites`,
`songhive:podcast:123` / `songhive:podcast_episode:123` for podcasts,
`songhive:remote:<object_id>` for federated content, and
`songhive:<http(s) url>` for direct URL lookups.
