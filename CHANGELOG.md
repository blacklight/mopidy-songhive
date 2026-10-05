# Changelog

## 0.1.5

- `feat`: Playlists gained a `playlist_format` setting that formats
  display names with `{name}`, `{provider}` and `{owner}` keys, so
  same-named playlists synced from different external providers can
  be told apart (e.g. `{name} [{provider}]`); the owner is fetched
  on demand, and the decorated name is never written back to the
  server on rename.
  ([`e54845e`](https://git.platypush.tech/blacklight/mopidy-songhive/commit/e54845ed5c737deb567cb52eb530a00063d460cc)).

## 0.1.4

- `chore`: Temporarily mark the extension as compatible also with Mopidy < 4.
  There may be some minor features missing, but at least this makes the
  extension usable also with system-installed versions of Mopidy until major
  distros adopt the version 4.

## 0.1.3

- `perf`: Track, podcast episode and remote object payloads are now
  cached on disk (SQLite in the extension cache dir) and seeded from
  collection listings, so browsing a library/playlist/podcast no longer
  triggers one API request per track on lookup. Metadata is re-fetched
  on playback to stay fresh, and a 404 evicts stale entries.
- `perf`: Image lookups and federated search hits are fetched
  concurrently instead of sequentially.

## 0.1.2

- `ci`: Fixed artifact upload to PyPI.

## 0.1.1

First public release.

Support for libraries, playlists, artists, albums, favorites, genres and tags.
