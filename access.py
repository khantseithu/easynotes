"""Password sign-in, so the app can be opened from a phone that is away from home."""
import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from http.cookies import CookieError, SimpleCookie

COOKIE = "easynotes"
MAX_FAILS = 10
FAIL_WINDOW = 600
# A proxy or tunnel on the Mac sends requests from 127.0.0.1, so a request with these headers is not local.
PROXY_HEADERS = ("X-Forwarded-For", "Forwarded", "X-Real-IP", "CF-Connecting-IP", "Tailscale-User-Login")


class Gate:
    """Lets requests from this Mac through, and asks every other device for the password.

    With no password, every request goes through, as before.
    """

    def __init__(self, password, key_path):
        self.password = password or ""
        self.token = ""
        self.fails = {}
        self.lock = threading.Lock()
        if self.password:
            key_path.parent.mkdir(exist_ok=True)
            if not key_path.exists():
                key_path.write_bytes(secrets.token_bytes(32))
                key_path.chmod(0o600)
            # The cookie depends on the password, so a new password signs out every device.
            self.token = hmac.new(key_path.read_bytes(), self.password.encode(), hashlib.sha256).hexdigest()

    @property
    def on(self):
        return bool(self.password)

    def local(self, client_ip, headers):
        try:
            loopback = ipaddress.ip_address(client_ip).is_loopback
        except ValueError:
            return False
        return loopback and not any(headers.get(h) for h in PROXY_HEADERS)

    def allowed(self, client_ip, headers):
        if not self.on or self.local(client_ip, headers):
            return True
        try:
            cookie = SimpleCookie(headers.get("Cookie", ""))
        except CookieError:
            cookie = {}
        return COOKIE in cookie and hmac.compare_digest(cookie[COOKIE].value, self.token)

    def check(self, password):
        return hmac.compare_digest((password or "").encode(), self.password.encode())

    def blocked(self, client_ip):
        now = time.time()
        with self.lock:
            recent = [t for t in self.fails.get(client_ip, []) if now - t < FAIL_WINDOW]
            self.fails[client_ip] = recent
            return len(recent) >= MAX_FAILS

    def sign_in(self, client_ip, password):
        """The Set-Cookie value for a right password, or None. Wrong guesses are slow and limited."""
        if self.blocked(client_ip):
            return None
        if self.on and self.check(password):
            with self.lock:
                self.fails.pop(client_ip, None)
            return f"{COOKIE}={self.token}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"
        with self.lock:
            self.fails.setdefault(client_ip, []).append(time.time())
        time.sleep(1)
        return None
