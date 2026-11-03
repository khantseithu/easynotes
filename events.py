"""Live updates. The server publishes each change here, and every open app gets it as a Server-Sent Event."""
import itertools
import json
import queue
import threading
from contextlib import contextmanager

PING_SECS = 15


class Bus:
    def __init__(self):
        self.lock = threading.Lock()
        self.queues = set()
        self.seq = itertools.count(1)

    def publish(self, kind, data=None):
        """Send an event to every open stream. Returns its number, which only goes up."""
        with self.lock:
            seq = next(self.seq)
            msg = f"event: {kind}\ndata: {json.dumps({**(data or {}), 'seq': seq}, ensure_ascii=False)}\n\n".encode()
            for q in self.queues:
                q.put(msg)
        return seq

    @contextmanager
    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            self.queues.add(q)
        try:
            yield q
        finally:
            with self.lock:
                self.queues.discard(q)

    def stream(self, write, ping=PING_SECS):
        """Write events until the client goes away. A comment line every few seconds finds closed connections."""
        with self.subscribe() as q:
            try:
                write(b"retry: 3000\n\n")
                while True:
                    try:
                        write(q.get(timeout=ping))
                    except queue.Empty:
                        write(b": ping\n\n")
            except OSError:
                pass


class Job(dict):
    """A job that tells the open apps about each change. Its seq is the number of the last event it sent."""

    def __init__(self, bus, **fields):
        super().__init__(fields)
        self.bus = bus

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.changed()

    def update(self, *args, **fields):
        super().update(*args, **fields)
        self.changed()

    def changed(self):
        super().__setitem__("seq", self.bus.publish("job", self))
