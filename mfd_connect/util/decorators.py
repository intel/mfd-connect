# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for decorator implementations."""

from functools import wraps, cache
from typing import Any, Callable


def conditional_cache(method: Callable) -> Callable:
    """
    Define decorator to conditionally cache the method output based on the attribute of the class.

    :param method: Method to be decorated.
    :return: Wrapper method.
    """

    @wraps(method)
    def wrapper(self: Any, *args, **kwargs) -> Callable:
        """
        Wrap the method to cache the output.

        :param self: Class instance.
        """
        if not hasattr(self, "_cached_methods"):
            self._cached_methods = {}

        if self.cache_system_data:
            if method not in self._cached_methods:

                @cache
                @wraps(method)
                def cached_method(*args, **kwargs) -> Callable:
                    """Cache the method output."""
                    return method(self, *args, **kwargs)

                self._cached_methods[method] = cached_method
            return self._cached_methods[method](*args, **kwargs)
        else:
            return method(self, *args, **kwargs)

    return wrapper


def clear_system_data_cache(method: Callable) -> Callable:
    """
    Define decorator to clear the system data cache.

    :param method: Method to be decorated.
    :return: Wrapped method.
    """

    @wraps(method)
    def wrapper(self: Any, *args, **kwargs) -> Callable:
        """
        Wrap the method to clear system data from the cache.

        Store the current value of cache_system_data, set it to False, execute the method
        and restore the original value.

        :param self: Class instance.
        """
        _temp_cache_system_data = self.cache_system_data
        self.cache_system_data = False
        self._cached_methods = {}
        try:
            result = method(self, *args, **kwargs)
        finally:
            self.cache_system_data = _temp_cache_system_data
        return result

    return wrapper
