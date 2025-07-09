# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Unit Test Module for Decorators utils."""

import pytest
from unittest.mock import patch

from mfd_connect.util.decorators import conditional_cache


class TestClass:
    def __init__(self, cache_system_data):
        """Init."""
        self.cache_system_data = cache_system_data
        self._cached_methods = {}

    @conditional_cache
    def sample_method(self, x):
        return x * 2


class TestConditionalCache:
    @pytest.fixture
    def obj_with_cache(self):
        return TestClass(cache_system_data=True)

    @pytest.fixture
    def obj_without_cache(self):
        return TestClass(cache_system_data=False)

    def test_conditional_cache_with_cache(self, obj_with_cache):
        with patch.object(TestClass, "sample_method", wraps=obj_with_cache.sample_method) as mock_method:
            assert obj_with_cache.sample_method(2) == 4
            assert obj_with_cache.sample_method(2) == 4
            assert mock_method.called
            assert obj_with_cache._cached_methods is not {}

    def test_conditional_cache_cache_disabled_after_first_call(self, obj_with_cache):
        with patch.object(TestClass, "sample_method", wraps=obj_with_cache.sample_method) as mock_method:
            result1 = obj_with_cache.sample_method(2)
            obj_with_cache.cache_system_data = False
            result2 = obj_with_cache.sample_method(2)
            assert result1 == 4
            assert result2 == 4
            assert mock_method.call_count == 2

    def test_conditional_cache_without_cache(self):
        cache_off = TestClass(cache_system_data=False)
        assert conditional_cache(cache_off.sample_method(2)) is not None
        assert cache_off._cached_methods == {}
        cache_on = TestClass(cache_system_data=True)
        conditional_cache(cache_on.sample_method(2))
        assert cache_on._cached_methods[cache_on.sample_method.__wrapped__] is not None
        cache_off2 = TestClass(cache_system_data=False)
        assert conditional_cache(cache_off2.sample_method(2)) is not None
        assert cache_off2._cached_methods == {}
