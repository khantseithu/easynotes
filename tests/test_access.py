import tempfile
import unittest
from pathlib import Path
from unittest import mock

import access


class GateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.key = Path(self.dir.name) / "notes" / ".auth-key"
        self.gate = access.Gate("secret", self.key)

    def tearDown(self):
        self.dir.cleanup()

    def test_no_password_lets_everyone_in(self):
        key = Path(self.dir.name) / "other" / ".auth-key"
        gate = access.Gate("", key)
        self.assertFalse(gate.on)
        self.assertTrue(gate.allowed("192.168.1.20", {}))
        self.assertFalse(key.exists())

    def test_this_mac_needs_no_password(self):
        self.assertTrue(self.gate.allowed("127.0.0.1", {}))
        self.assertTrue(self.gate.allowed("::1", {}))

    def test_requests_through_a_proxy_are_not_local(self):
        self.assertFalse(self.gate.allowed("127.0.0.1", {"X-Forwarded-For": "203.0.113.9"}))
        self.assertFalse(self.gate.allowed("127.0.0.1", {"Tailscale-User-Login": "me@example.com"}))

    def test_other_devices_need_the_cookie(self):
        self.assertFalse(self.gate.allowed("100.64.0.2", {}))
        with mock.patch("access.time.sleep"):
            self.assertIsNone(self.gate.sign_in("100.64.0.2", "wrong"))
        cookie = self.gate.sign_in("100.64.0.2", "secret")
        value = cookie.split(";")[0]
        self.assertIn("HttpOnly", cookie)
        self.assertTrue(self.gate.allowed("100.64.0.2", {"Cookie": f"theme=dark; {value}"}))
        self.assertFalse(self.gate.allowed("100.64.0.2", {"Cookie": "easynotes=forged"}))
        self.assertFalse(self.gate.allowed("100.64.0.2", {"Cookie": "bad\x00cookie"}))

    def test_the_password_alone_is_not_a_sign_in(self):
        # Only sign_in checks the password, so every guess is slow and counted.
        self.assertFalse(self.gate.allowed("100.64.0.2", {"Authorization": "Bearer secret"}))

    def test_the_cookie_survives_a_restart_but_not_a_new_password(self):
        self.assertEqual(access.Gate("secret", self.key).token, self.gate.token)
        self.assertNotEqual(access.Gate("other", self.key).token, self.gate.token)

    def test_too_many_wrong_guesses_block_sign_in(self):
        with mock.patch("access.time.sleep"):
            for _ in range(access.MAX_FAILS):
                self.gate.sign_in("100.64.0.3", "wrong")
        self.assertIsNone(self.gate.sign_in("100.64.0.3", "secret"))
        self.assertIsNotNone(self.gate.sign_in("100.64.0.4", "secret"))


if __name__ == "__main__":
    unittest.main()
