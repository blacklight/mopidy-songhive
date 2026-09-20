# Changelog

## Unreleased

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
