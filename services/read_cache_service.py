"""Bounded, mutation-safe read caches shared by all SQLite browse consumers."""
from copy import deepcopy
from functools import lru_cache, wraps

from services.database_service import database_change_token, resolve_database_path


def cached_database_read(maxsize=128):
    def decorate(function):
        @lru_cache(maxsize=maxsize)
        def read(path, token, args, kwargs):
            return function(path, *args, **dict(kwargs))

        @wraps(function)
        def wrapped(db_path=None, *args, **kwargs):
            path = resolve_database_path(db_path)
            key = (path, database_change_token(path), args, tuple(sorted(kwargs.items())))
            # Explicit connections belong to the caller's transaction/snapshot.
            if kwargs.get('_connection') is not None:
                return function(path, *args, **kwargs)
            try:
                hash(key)
            except TypeError:
                return function(path, *args, **kwargs)
            return deepcopy(read(*key))
        wrapped.cache_clear = read.cache_clear
        return wrapped
    return decorate
