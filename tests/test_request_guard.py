import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer

import ytnotes


class RequestGuardTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ytnotes.Handler)
        self.server.RequestHandlerClass.log_message = lambda *a: None
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.local = f"127.0.0.1:{self.server.server_address[1]}"

    def status(self, method, path, **headers):
        conn = http.client.HTTPConnection(*self.server.server_address)
        self.addCleanup(conn.close)
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", headers.pop("host", self.local))
        for name, value in headers.items():
            conn.putheader(name, value)
        conn.putheader("Content-Length", "0")
        conn.endheaders()
        return conn.getresponse().status

    def test_a_rebound_host_cannot_read(self):
        self.assertEqual(self.status("GET", "/api/voices", host="evil.example:8765"), 403)

    def test_local_hosts_can_read(self):
        self.assertEqual(self.status("GET", "/api/voices"), 200)
        self.assertEqual(self.status("GET", "/api/voices", host="localhost:8765"), 200)

    def test_a_network_address_cannot_read(self):
        self.assertEqual(self.status("GET", "/api/voices", host="192.168.1.20:8765"), 403)

    def test_another_site_cannot_change_anything(self):
        for method in ("POST", "DELETE"):
            self.assertEqual(self.status(method, "/api/missing", Origin="https://evil.example"), 403)
            self.assertEqual(self.status(method, "/api/missing", Origin="null"), 403)

    def test_the_app_and_the_extension_can_change_things(self):
        self.assertEqual(self.status("POST", "/api/missing", Origin=f"http://{self.local}"), 404)
        self.assertEqual(self.status("POST", "/api/missing", Origin="chrome-extension://abc"), 404)
        self.assertEqual(self.status("POST", "/api/missing"), 404)


if __name__ == "__main__":
    unittest.main()
