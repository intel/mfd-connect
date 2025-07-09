# Copyright (C) 2025 Intel Corporation
# SPDX-License-Identifier: MIT
"""Module for batch queue implementation."""

import queue
from itertools import count
from collections import deque
from typing import Iterable, List


class BatchQueue(queue.Queue):
    """
    Queue with get_many() and put_many() methods added.

    Batch queue is used to reduce the number of remote calls to the queues on the other side of a Connection connection.
    The class is especially useful in case the queue is filled with a lot of items before the consumption.
    """

    def get_many(self, limit: int = None) -> List:
        """
        Get multiple items from the queue.

        Gets the items from the queue until the queue is empty or the limit is reached.
        If the queue is empty - an empty list is returned.
        :param limit: Maximum number of items to get.
        :return: List of items from the queue.
        """
        if limit is None:
            limiting_iterator = count()  # Unlimited
        else:
            limiting_iterator = range(limit)  # Limited by the 'number'

        result = []
        try:
            for _ in limiting_iterator:
                result.append(self.get_nowait())
        except queue.Empty:
            pass  # Can't get any more

        return result

    def put_many(self, seq: Iterable) -> List:
        """
        Put multiple items into the queue.

        Tries to put as many items from seq as possible into the queue
        until either the seq is empty or the queue is full.

        If the queue gets filled up before the seq is depleted -
        the remainder is returned as a list.
        :param seq: Sequence holding items to put into the queue.
        :return: The list of items which didn't fit into the queue.
        """
        seq_deque = deque(seq)

        try:
            while True:
                item = seq_deque.popleft()
                self.put_nowait(item)
        except queue.Full:
            # queue is full
            seq_deque.appendleft(item)
        except IndexError:
            # seq is empty
            pass

        return list(seq_deque)  # Return the remainder
