import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import events
import ytnotes


def parse(msg):
    lines = dict(line.split(": ", 1) for line in msg.decode().strip().splitlines())
    return lines["event"], json.loads(lines["data"])


class BusTests(unittest.TestCase):
    def test_publish_reaches_each_subscriber_as_an_sse_message(self):
        bus = events.Bus()
        with bus.subscribe() as a, bus.subscribe() as b:
            seq = bus.publish("notes", {"id": "aaaaaaaaaaa"})
            for q in (a, b):
                kind, data = parse(q.get_nowait())
                self.assertEqual(kind, "notes")
                self.assertEqual(data, {"id": "aaaaaaaaaaa", "seq": seq})

    def test_numbers_only_go_up(self):
        bus = events.Bus()
        self.assertLess(bus.publish("daily"), bus.publish("daily"))

    def test_closed_subscriber_gets_nothing(self):
        bus = events.Bus()
        with bus.subscribe() as q:
            pass
        bus.publish("daily")
        self.assertTrue(q.empty())
        self.assertFalse(bus.queues)

    def test_stream_pings_and_stops_when_the_client_goes_away(self):
        bus = events.Bus()
        written = []

        def write(data):
            written.append(data)
            if len(written) == 3:
                raise BrokenPipeError

        bus.stream(write, ping=0.01)
        self.assertEqual(written[0], b"retry: 3000\n\n")
        self.assertEqual(written[1], b": ping\n\n")
        self.assertFalse(bus.queues)


class JobTests(unittest.TestCase):
    def test_each_change_is_published_with_the_full_job(self):
        bus = events.Bus()
        job = events.Job(bus, id="j1", status="running", message="Starting…")
        with bus.subscribe() as q:
            job["message"] = "Reading the playlist…"
            job.update(status="done", ids=["aaaaaaaaaaa"])
            first, second = parse(q.get_nowait())[1], parse(q.get_nowait())[1]
        self.assertEqual(first["message"], "Reading the playlist…")
        self.assertEqual(second["status"], "done")
        self.assertEqual(second["ids"], ["aaaaaaaaaaa"])
        self.assertEqual(job["seq"], second["seq"])
        self.assertLess(first["seq"], second["seq"])

    def test_job_is_still_plain_json(self):
        job = events.Job(events.Bus(), id="j1", status="running")
        self.assertEqual(json.loads(json.dumps(job)), {"id": "j1", "status": "running"})


class ServerStreamTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "index.json").write_text(json.dumps([{"id": "aaaaaaaaaaa", "title": "Growth basics"}]))
        patches = [mock.patch.object(ytnotes, "BUS", events.Bus()), mock.patch.object(ytnotes, "NOTES", tmp),
                   mock.patch.object(ytnotes, "INDEX", tmp / "index.json"),
                   mock.patch.object(ytnotes, "HIGHLIGHTS", tmp / "highlights.json")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ytnotes.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def open_stream(self):
        stream = urllib.request.urlopen(self.base + "/api/events", timeout=5)
        self.addCleanup(stream.close)
        while not ytnotes.BUS.queues:
            threading.Event().wait(0.01)
        return stream

    def next_event(self, stream):
        while True:
            msg = b""
            while not msg.endswith(b"\n\n"):
                msg += stream.readline()
            if msg.startswith(b"event:"):
                return parse(msg)

    def test_stream_is_server_sent_events(self):
        self.assertEqual(self.open_stream().headers["Content-Type"], "text/event-stream")

    def test_marking_a_note_read_reaches_open_streams(self):
        stream = self.open_stream()
        self.post("/api/notes/aaaaaaaaaaa/read", {"read": True})
        kind, data = self.next_event(stream)
        self.assertEqual((kind, data["id"]), ("notes", "aaaaaaaaaaa"))

    def test_highlights_reach_open_streams(self):
        stream = self.open_stream()
        self.post("/api/notes/aaaaaaaaaaa/highlights", {"quote": "Churn matters"})
        kind, data = self.next_event(stream)
        self.assertEqual((kind, data["id"]), ("highlights", "aaaaaaaaaaa"))

if __name__ == "__main__":
    unittest.main()
