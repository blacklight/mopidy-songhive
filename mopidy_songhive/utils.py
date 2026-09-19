import contextlib
import functools
import logging
import time
import weakref
from typing import Optional

logger = logging.getLogger(__name__)


class memoize:
    """Simple time-based per-instance memoization decorator.

    Caches results keyed on the call arguments (positional and keyword);
    entries expire after ``ttl`` seconds, or never when ``ttl`` is
    ``None``. Calls with unhashable arguments are not cached. Borrowed
    from mopidy-soundcloud/mopidy-jellyfin.

    Intended for methods: entries live in a per-instance table held
    through weak references, so a garbage-collected instance drops its
    cache instead of being pinned by a shared, decorator-level dict
    (see flake8-bugbear B019).

    The wrapped function gains two helpers mirroring
    ``functools.lru_cache``:

    * ``cache_clear()`` — drop every cached entry, or only the entries
      of the instance passed as argument.
    * ``cache_invalidate(*args, **kwargs)`` — drop the entry for one
      call; takes the same arguments as the call, ``self`` included.
    """

    def __init__(self, ttl: Optional[int] = 60):
        self.caches: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self.ttl = ttl

    def _key(self, args, kwargs):
        return args + tuple(sorted(kwargs.items()))

    def _instance_cache(self, instance, create=False):
        """The cache dict for ``instance``, or None when it can't be keyed."""
        try:
            if create:
                return self.caches.setdefault(instance, {})
            return self.caches.get(instance)
        except TypeError:
            return None

    def __call__(self, func):
        @functools.wraps(func)
        def _memoized(*args, **kwargs):
            store = (
                self._instance_cache(args[0], create=True) if args else None
            )
            if store is None:
                return func(*args, **kwargs)

            key = self._key(args[1:], kwargs)
            now = time.time()
            try:
                value, last_update = store[key]
                if self.ttl is None or now - last_update <= self.ttl:
                    return value
            except (KeyError, TypeError):
                pass

            value = func(*args, **kwargs)
            with contextlib.suppress(TypeError):
                store[key] = (value, now)
            return value

        def cache_clear(*args):
            if args:
                store = self._instance_cache(args[0])
                if store is not None:
                    store.clear()
            else:
                self.caches.clear()

        def cache_invalidate(*args, **kwargs):
            if not args:
                return
            store = self._instance_cache(args[0])
            if store is not None:
                with contextlib.suppress(TypeError):
                    store.pop(self._key(args[1:], kwargs), None)

        _memoized.cache_clear = cache_clear
        _memoized.cache_invalidate = cache_invalidate
        return _memoized
