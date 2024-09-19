from __future__ import annotations

from typing import TypedDict


class SplitQueueSize(TypedDict):
    # The total number of queues to create to split a single queue.
    # This number triggers the creation of the queues themselves
    # when the application starts.
    total: int
    # The number of queues to actually use. It has to be smaller or
    # equal to `total`.
    # This is the number of queues the router uses when the split
    # is enable on this queue.
    # This number exists in order to be able to safely increase or
    # decrease the number of queues as the queues have to be created
    # first, then we have to start consuming from them, only then
    # we can start producing.
    in_use: int


class SplitQueueTaskRoute(TypedDict):
    """
    This is used to provide the routes tasks invocations have to be
    routed to when the Celery router is used.
    """

    # This represents both the name of the default queue in use when
    # the router is not deployed and the prefix for all split queue
    # names for this task.
    #
    # Example: my_queue, becomes my_queue_1, my_queue_2 if there are
    # two split queues.
    default_queue: str

    # Configures the number of queues to create and to use.
    queues_config: SplitQueueSize
