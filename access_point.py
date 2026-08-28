#!/usr/bin/env python3
ADMIN_USERNAME = "protogen"
ADMIN_PASSWORD = "change-me-before-use"

import hmac
import html
import json
import os
import secrets
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List
from urllib.parse import parse_qs, urlparse

# User Values: These may need to be changed to match the Pi and the wireless setup.
ACCESS_POINT_SSID = "ProtoPi"
ACCESS_POINT_PASSPHRASE = "protopi-hotspot"
ACCESS_POINT_INTERFACE = "wlan0"
ACCESS_POINT_CHANNEL = 6
ACCESS_POINT_ADDRESS = "192.168.4.1"
ACCESS_POINT_PREFIX = 24
CONSOLE_PORT = 8080

# Configuration values: These can be changed to personal preference.
SESSION_IDLE_TIMEOUT_MS = 900000
COMMAND_TIMEOUT_MS = 20000
NMCLI_TIMEOUT_MS = 30000
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_LOCKOUT_MS = 60000
CONSOLE_SHELL = "/bin/bash"

# Constants: These should not need to be changed.
CONNECTION_NAME = "protopi-ap"
SESSION_COOKIE_NAME = "protopi_session"
CSRF_HEADER_NAME = "X-ProtoPi-Token"
WORKING_DIRECTORY_MARKER = "\x1eprotopi-cwd\x1e"
DEFAULT_ADMIN_PASSWORD = "change-me-before-use"
MINIMUM_PASSPHRASE_LENGTH = 8
MAXIMUM_PASSPHRASE_LENGTH = 63
MINIMUM_SSID_LENGTH = 1
MAXIMUM_SSID_LENGTH = 32
MAXIMUM_REQUEST_BYTES = 65536
PROTECTED_MANAGEMENT_FRAMES_DISABLED = "1"
UNSET_REGULATORY_DOMAIN = "country 00:"
TWO_GHZ_CHANNELS = range(1, 15)
FIVE_GHZ_CHANNELS = range(32, 178)


# Class: SettingsError marks a configuration value the program cannot start with.
class SettingsError(Exception):
    pass


# Class: ConsoleSession holds the per-login state of one signed-in admin browser.
@dataclass
class ConsoleSession:
    token: str
    csrf_token: str
    remote_address: str
    working_directory: str
    last_seen_ms: float = 0.0


# Class: LoginThrottle counts failed logins per client so guessing gets slow.
@dataclass
class LoginThrottle:
    failure_count: int = 0
    locked_until_ms: float = 0.0


# Contract: Return the monotonic clock in milliseconds.
def now_ms() -> float:
    return time.monotonic() * 1000


# Contract: Reject settings that would otherwise fail deep inside nmcli or the server.
def validate_settings() -> None:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        raise SettingsError("ADMIN_USERNAME and ADMIN_PASSWORD must both be set.")

    passphrase_length = len(ACCESS_POINT_PASSPHRASE)

    if not MINIMUM_PASSPHRASE_LENGTH <= passphrase_length <= MAXIMUM_PASSPHRASE_LENGTH:
        raise SettingsError(
            "ACCESS_POINT_PASSPHRASE must be "
            f"{MINIMUM_PASSPHRASE_LENGTH}-{MAXIMUM_PASSPHRASE_LENGTH} characters."
        )

    if not MINIMUM_SSID_LENGTH <= len(ACCESS_POINT_SSID) <= MAXIMUM_SSID_LENGTH:
        raise SettingsError(
            f"ACCESS_POINT_SSID must be "
            f"{MINIMUM_SSID_LENGTH}-{MAXIMUM_SSID_LENGTH} characters."
        )

    if ACCESS_POINT_CHANNEL not in TWO_GHZ_CHANNELS:
        if ACCESS_POINT_CHANNEL not in FIVE_GHZ_CHANNELS:
            raise SettingsError(
                f"ACCESS_POINT_CHANNEL {ACCESS_POINT_CHANNEL} is not a valid channel."
            )

    if not 1 <= CONSOLE_PORT <= 65535:
        raise SettingsError("CONSOLE_PORT must be between 1 and 65535.")

    if ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
        print("Warning: ADMIN_PASSWORD is still the shipped default; change it.")


# Class: AccessPointController drives the NetworkManager hotspot on the Pi.
class AccessPointController:
    # Contract: Store hotspot settings and locate the nmcli binary if it is present.
    def __init__(
        self,
        ssid: str = ACCESS_POINT_SSID,
        passphrase: str = ACCESS_POINT_PASSPHRASE,
        interface: str = ACCESS_POINT_INTERFACE,
        channel: int = ACCESS_POINT_CHANNEL,
        address: str = ACCESS_POINT_ADDRESS,
        prefix: int = ACCESS_POINT_PREFIX,
    ) -> None:
        self.ssid = ssid
        self.passphrase = passphrase
        self.interface = interface
        self.channel = channel
        self.address = address
        self.prefix = prefix
        self.nmcli_path = shutil.which("nmcli")
        self.active = False

    # Contract: Return the wireless band that follows from the configured channel.
    @property
    def band(self) -> str:
        return "bg" if self.channel in TWO_GHZ_CHANNELS else "a"

    # Contract: Run one nmcli invocation and return it, or None when nmcli is missing.
    def run_nmcli(self, arguments: List[str]) -> subprocess.CompletedProcess | None:
        if self.nmcli_path is None:
            return None

        return subprocess.run(
            [self.nmcli_path, *arguments],
            capture_output=True,
            text=True,
            timeout=NMCLI_TIMEOUT_MS / 1000,
        )

    # Contract: Report why the hotspot cannot come up and leave the console running.
    def report_unavailable(self, reason: str) -> None:
        print(f"Warning: access point not started ({reason}).")
        print("Warning: the admin console will listen on every interface instead.")

    # Contract: Delete any stale profile so the hotspot matches the current settings.
    def remove_existing_profile(self) -> None:
        self.run_nmcli(["connection", "delete", CONNECTION_NAME])

    # Contract: Create the hotspot profile from the configured settings.
    def create_profile(self) -> subprocess.CompletedProcess | None:
        created = self.run_nmcli(
            [
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                self.interface,
                "con-name",
                CONNECTION_NAME,
                "autoconnect",
                "no",
                "ssid",
                self.ssid,
            ]
        )

        if created is None or created.returncode != 0:
            return created

        return self.run_nmcli(
            [
                "connection",
                "modify",
                CONNECTION_NAME,
                "802-11-wireless.mode",
                "ap",
                "802-11-wireless.band",
                self.band,
                "802-11-wireless.channel",
                str(self.channel),
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.proto",
                "rsn",
                "wifi-sec.pairwise",
                "ccmp",
                "wifi-sec.group",
                "ccmp",
                "wifi-sec.pmf",
                PROTECTED_MANAGEMENT_FRAMES_DISABLED,
                "wifi-sec.psk",
                self.passphrase,
                "ipv4.method",
                "shared",
                "ipv4.addresses",
                f"{self.address}/{self.prefix}",
                "ipv6.method",
                "disabled",
            ]
        )

    # Contract: Return the output of a diagnostic command, or "" when it cannot run.
    def read_command_output(self, arguments: List[str]) -> str:
        binary_path = shutil.which(arguments[0])

        if binary_path is None:
            return ""

        try:
            completed = subprocess.run(
                [binary_path, *arguments[1:]],
                capture_output=True,
                text=True,
                timeout=NMCLI_TIMEOUT_MS / 1000,
            )
        except (OSError, subprocess.SubprocessError) as error:
            print(f"Warning: could not run {arguments[0]} ({error}).")
            return ""

        return completed.stdout

    # Contract: Warn about the radio conditions that make an AP time out on startup.
    def report_radio_warnings(self) -> None:
        if "Soft blocked: yes" in self.read_command_output(["rfkill", "list", "wifi"]):
            print(
                "Warning: the Wi-Fi radio is soft blocked; run 'rfkill unblock wifi'."
            )

        if UNSET_REGULATORY_DOMAIN in self.read_command_output(["iw", "reg", "get"]):
            print("Warning: no WLAN country is set, which blocks AP mode on the Pi.")
            print("Warning: set one with 'raspi-config' under Localisation Options.")

    # Contract: Bring the hotspot up and report whether it is now serving clients.
    def start(self) -> bool:
        if self.nmcli_path is None:
            self.report_unavailable("nmcli was not found on this system")
            return False

        if hasattr(os, "geteuid") and os.geteuid() != 0:
            print("Warning: not running as root; nmcli may refuse to build the AP.")

        self.report_radio_warnings()

        try:
            self.remove_existing_profile()
            configured = self.create_profile()

            if configured is None or configured.returncode != 0:
                detail = configured.stderr.strip() if configured else "nmcli missing"
                self.remove_existing_profile()
                self.report_unavailable(detail)
                return False

            raised = self.run_nmcli(["connection", "up", CONNECTION_NAME])
        except (OSError, subprocess.SubprocessError) as error:
            self.report_unavailable(str(error))
            return False

        if raised is None or raised.returncode != 0:
            detail = raised.stderr.strip() if raised else "nmcli missing"
            self.remove_existing_profile()
            self.report_unavailable(detail)
            return False

        self.active = True
        print(f"Access point '{self.ssid}' is up on {self.interface} ({self.address}).")
        return True

    # Contract: List the MAC addresses currently associated with the hotspot.
    def connected_stations(self) -> List[str]:
        iw_path = shutil.which("iw")

        if iw_path is None or not self.active:
            return []

        try:
            dumped = subprocess.run(
                [iw_path, "dev", self.interface, "station", "dump"],
                capture_output=True,
                text=True,
                timeout=NMCLI_TIMEOUT_MS / 1000,
            )
        except (OSError, subprocess.SubprocessError) as error:
            print(f"Warning: could not list wireless clients ({error}).")
            return []

        return [
            line.split()[1]
            for line in dumped.stdout.splitlines()
            if line.startswith("Station ")
        ]

    # Contract: Take the hotspot down and remove the profile it was created from.
    def shutdown(self) -> None:
        if not self.active:
            return

        try:
            self.run_nmcli(["connection", "down", CONNECTION_NAME])
            self.remove_existing_profile()
        except (OSError, subprocess.SubprocessError) as error:
            print(f"Warning: could not tear down the access point ({error}).")

        self.active = False
        print("Access point stopped.")


# Class: AdminConsoleServer owns the login sessions and runs the submitted commands.
class AdminConsoleServer(ThreadingHTTPServer):
    daemon_threads = True

    # Contract: Prepare the session tables before the socket starts accepting clients.
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type,
        access_point: AccessPointController,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.access_point = access_point
        self.sessions: Dict[str, ConsoleSession] = {}
        self.throttles: Dict[str, LoginThrottle] = {}
        self.state_lock = threading.Lock()
        self.home_directory = str(Path.home())

    # Contract: Return whether the given client may still attempt a login.
    def login_allowed(self, remote_address: str) -> bool:
        with self.state_lock:
            throttle = self.throttles.get(remote_address)

            if throttle is None:
                return True

            return now_ms() >= throttle.locked_until_ms

    # Contract: Count a failed login and lock the client out once the limit is hit.
    def record_failed_login(self, remote_address: str) -> None:
        with self.state_lock:
            throttle = self.throttles.setdefault(remote_address, LoginThrottle())
            throttle.failure_count += 1

            if throttle.failure_count >= LOGIN_ATTEMPT_LIMIT:
                throttle.failure_count = 0
                throttle.locked_until_ms = now_ms() + LOGIN_LOCKOUT_MS
                print(f"Warning: login lockout for {remote_address}.")

    # Contract: Check the submitted credentials without leaking timing information.
    def credentials_match(self, username: str, password: str) -> bool:
        username_matches = hmac.compare_digest(
            username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8")
        )
        password_matches = hmac.compare_digest(
            password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8")
        )
        return username_matches and password_matches

    # Contract: Create a session for a successful login and return it.
    def create_session(self, remote_address: str) -> ConsoleSession:
        session = ConsoleSession(
            token=secrets.token_urlsafe(32),
            csrf_token=secrets.token_urlsafe(32),
            remote_address=remote_address,
            working_directory=self.home_directory,
            last_seen_ms=now_ms(),
        )

        with self.state_lock:
            self.sessions[session.token] = session
            self.throttles.pop(remote_address, None)

        print(f"Admin console login from {remote_address}.")
        return session

    # Contract: Return the live session for a cookie token, dropping expired ones.
    def get_session(self, token: str | None) -> ConsoleSession | None:
        if not token:
            return None

        with self.state_lock:
            session = self.sessions.get(token)

            if session is None:
                return None

            if now_ms() - session.last_seen_ms > SESSION_IDLE_TIMEOUT_MS:
                del self.sessions[token]
                return None

            session.last_seen_ms = now_ms()
            return session

    # Contract: Forget the session behind the given token.
    def end_session(self, token: str | None) -> None:
        if not token:
            return

        with self.state_lock:
            self.sessions.pop(token, None)

    # Contract: Build the shell script that runs one command and reports the new cwd.
    def build_script(self, session: ConsoleSession, command: str) -> str:
        return (
            f"cd {shlex.quote(session.working_directory)} || cd /\n"
            f"{command}\n"
            "protopi_exit_code=$?\n"
            f'printf %s "{WORKING_DIRECTORY_MARKER}$PWD"\n'
            "exit $protopi_exit_code\n"
        )

    # Contract: Split a finished command's stdout into console output and the new cwd.
    def split_working_directory(
        self, session: ConsoleSession, standard_output: str
    ) -> str:
        marker_index = standard_output.rfind(WORKING_DIRECTORY_MARKER)

        if marker_index < 0:
            return standard_output

        reported_directory = standard_output[
            marker_index + len(WORKING_DIRECTORY_MARKER) :
        ].strip()

        if reported_directory:
            with self.state_lock:
                session.working_directory = reported_directory

        return standard_output[:marker_index]

    # Contract: Run one console command and return its output, exit code, and cwd.
    def run_command(self, session: ConsoleSession, command: str) -> dict:
        try:
            completed = subprocess.run(
                [CONSOLE_SHELL, "-c", self.build_script(session, command)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=COMMAND_TIMEOUT_MS / 1000,
            )
        except subprocess.TimeoutExpired:
            return {
                "output": f"Command timed out after {COMMAND_TIMEOUT_MS} ms.",
                "exit_code": 124,
                "working_directory": session.working_directory,
            }
        except OSError as error:
            return {
                "output": f"Could not run command: {error}",
                "exit_code": 127,
                "working_directory": session.working_directory,
            }

        console_output = self.split_working_directory(session, completed.stdout)

        return {
            "output": console_output + completed.stderr,
            "exit_code": completed.returncode,
            "working_directory": session.working_directory,
        }


# Class: ConsoleRequestHandler serves the login page, the console page, and /run.
class ConsoleRequestHandler(BaseHTTPRequestHandler):
    server_version = "ProtoPiConsole/1.0"
    protocol_version = "HTTP/1.1"

    # Contract: Print one compact line per request instead of the default log format.
    def log_message(self, format: str, *args) -> None:
        print(f"{self.client_address[0]} {format % args}")

    # Contract: Return the client address used for throttling and session ownership.
    @property
    def remote_address(self) -> str:
        return self.client_address[0]

    # Contract: Return the session cookie token sent with this request, if any.
    def read_session_token(self) -> str | None:
        header = self.headers.get("Cookie")

        if not header:
            return None

        cookie = SimpleCookie()

        try:
            cookie.load(header)
        except CookieError as error:
            print(f"Warning: unreadable cookie header ({error}).")
            return None

        morsel = cookie.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel is not None else None

    # Contract: Read the request body, refusing anything larger than the size cap.
    def read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            print("Warning: request had a malformed Content-Length header.")
            return b""

        if length <= 0:
            return b""

        if length > MAXIMUM_REQUEST_BYTES:
            print(f"Warning: discarding an oversized {length} byte request body.")
            self.rfile.read(length)
            return b""

        return self.rfile.read(length)

    # Contract: Send a complete response with the given body, status, and headers.
    def send_body(
        self,
        body: bytes,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "text/html; charset=utf-8",
        extra_headers: List[tuple[str, str]] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")

        for name, value in extra_headers or []:
            self.send_header(name, value)

        self.end_headers()
        self.wfile.write(body)

    # Contract: Send a JSON payload to the client.
    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_body(body, status, "application/json; charset=utf-8")

    # Contract: Send an empty redirect to the given path.
    def send_redirect(
        self, location: str, extra_headers: List[tuple[str, str]] | None = None
    ) -> None:
        headers = [("Location", location), *(extra_headers or [])]
        self.send_body(b"", HTTPStatus.SEE_OTHER, "text/plain; charset=utf-8", headers)

    # Contract: Build the Set-Cookie header that carries a session token.
    def session_cookie_header(
        self, token: str, expire: bool = False
    ) -> tuple[str, str]:
        lifetime = 0 if expire else SESSION_IDLE_TIMEOUT_MS // 1000
        value = (
            f"{SESSION_COOKIE_NAME}={token}; HttpOnly; SameSite=Strict; "
            f"Path=/; Max-Age={lifetime}"
        )
        return ("Set-Cookie", value)

    # Contract: Serve the login page or the console page depending on the session.
    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path != "/":
            self.send_body(b"Not found", HTTPStatus.NOT_FOUND, "text/plain")
            return

        session = self.server.get_session(self.read_session_token())

        if session is None:
            query = parse_qs(urlparse(self.path).query)
            message = "Incorrect username or password." if "error" in query else ""

            if "locked" in query:
                message = f"Too many attempts. Wait {LOGIN_LOCKOUT_MS // 1000} seconds."

            self.send_body(render_login_page(message).encode("utf-8"))
            return

        self.send_body(render_console_page(self.server, session).encode("utf-8"))

    # Contract: Route the login, logout, and command endpoints.
    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path == "/login":
            self.handle_login()
        elif path == "/logout":
            self.handle_logout()
        elif path == "/run":
            self.handle_run()
        else:
            self.send_body(b"Not found", HTTPStatus.NOT_FOUND, "text/plain")

    # Contract: Check submitted credentials and start a session when they match.
    def handle_login(self) -> None:
        if not self.server.login_allowed(self.remote_address):
            self.send_redirect("/?locked")
            return

        fields = parse_qs(self.read_body().decode("utf-8", errors="replace"))
        username = fields.get("username", [""])[0]
        password = fields.get("password", [""])[0]

        if not self.server.credentials_match(username, password):
            self.server.record_failed_login(self.remote_address)
            self.send_redirect("/?error")
            return

        session = self.server.create_session(self.remote_address)
        self.send_redirect("/", [self.session_cookie_header(session.token)])

    # Contract: End the current session and return the browser to the login page.
    def handle_logout(self) -> None:
        token = self.read_session_token()
        self.server.end_session(token)
        self.send_redirect("/", [self.session_cookie_header("", expire=True)])

    # Contract: Run one submitted command for an authenticated session.
    def handle_run(self) -> None:
        session = self.server.get_session(self.read_session_token())

        if session is None:
            self.send_json({"error": "Session expired."}, HTTPStatus.UNAUTHORIZED)
            return

        if self.headers.get(CSRF_HEADER_NAME) != session.csrf_token:
            self.send_json({"error": "Bad request token."}, HTTPStatus.FORBIDDEN)
            return

        try:
            request = json.loads(self.read_body().decode("utf-8", errors="replace"))
        except ValueError as error:
            print(f"Warning: unreadable command payload ({error}).")
            self.send_json({"error": "Malformed request."}, HTTPStatus.BAD_REQUEST)
            return

        command = str(request.get("command", "")).strip()

        if not command:
            self.send_json({"error": "Empty command."}, HTTPStatus.BAD_REQUEST)
            return

        print(f"{self.remote_address} ran: {command}")
        self.send_json(self.server.run_command(session, command))


# Contract: Render the login page, showing the given message when one is present.
def render_login_page(message: str) -> str:
    banner = f'<p class="error">{html.escape(message)}</p>' if message else ""
    return LOGIN_PAGE_TEMPLATE.format(
        style=CONSOLE_STYLE,
        ssid=html.escape(ACCESS_POINT_SSID),
        banner=banner,
    )


# Contract: Render the console page for a signed-in session.
def render_console_page(server: AdminConsoleServer, session: ConsoleSession) -> str:
    station_count = len(server.access_point.connected_stations())
    access_point_state = "up" if server.access_point.active else "off"

    return CONSOLE_PAGE_TEMPLATE.format(
        style=CONSOLE_STYLE,
        script=CONSOLE_SCRIPT,
        ssid=html.escape(ACCESS_POINT_SSID),
        access_point_state=access_point_state,
        station_count=station_count,
        csrf_header=CSRF_HEADER_NAME,
        csrf_token=html.escape(session.csrf_token),
        working_directory=html.escape(session.working_directory),
        timeout_seconds=COMMAND_TIMEOUT_MS // 1000,
    )


# Contract: Start the hotspot, serve the admin console, and clean both up on exit.
def main() -> None:
    try:
        validate_settings()
    except SettingsError as error:
        print(f"Cannot start: {error}")
        return

    access_point = AccessPointController()
    access_point.start()

    bind_address = ACCESS_POINT_ADDRESS if access_point.active else "0.0.0.0"
    server = AdminConsoleServer(
        (bind_address, CONSOLE_PORT), ConsoleRequestHandler, access_point
    )

    print(f"Admin console on http://{bind_address}:{CONSOLE_PORT}/")
    print(f"Sign in as '{ADMIN_USERNAME}'. Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Exiting...")
    finally:
        server.shutdown()
        server.server_close()
        access_point.shutdown()


CONSOLE_STYLE = """
:root {
  color-scheme: dark;
  --background: #10121a;
  --panel: #191d29;
  --border: #2c3242;
  --text: #e6e9f2;
  --muted: #8f97ad;
  --accent: #29bf12;
  --error: #fe0b0b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 1rem;
  background: var(--background);
  color: var(--text);
  font-family: ui-monospace, "DejaVu Sans Mono", Menlo, Consolas, monospace;
  font-size: 15px;
  line-height: 1.45;
}
h1 { font-size: 1.1rem; margin: 0; letter-spacing: 0.08em; }
.card {
  max-width: 60rem;
  margin: 0 auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1rem;
}
.login { max-width: 22rem; margin-top: 12vh; }
header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}
.meta { color: var(--muted); font-size: 0.8rem; }
label { display: block; margin-top: 0.75rem; color: var(--muted); font-size: 0.8rem; }
input, button {
  font: inherit;
  color: var(--text);
  background: var(--background);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.5rem 0.6rem;
}
input { width: 100%; margin-top: 0.25rem; }
input:focus, button:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
button { cursor: pointer; }
button.primary { margin-top: 1rem; width: 100%; border-color: var(--accent); }
.error { color: var(--error); margin: 0.75rem 0 0; }
#output {
  height: 60vh;
  overflow: auto;
  margin: 0;
  padding: 0.75rem;
  background: var(--background);
  border: 1px solid var(--border);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
}
.exit-fail { color: var(--error); }
.echo { color: var(--accent); }
form.prompt { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
form.prompt input { flex: 1; }
#cwd { color: var(--muted); font-size: 0.8rem; margin-top: 0.5rem; }
"""

LOGIN_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ProtoPi admin</title>
<style>{style}</style>
</head>
<body>
<main class="card login">
<h1>PROTOPI ADMIN</h1>
<p class="meta">{ssid}</p>
<form method="post" action="/login">
<label for="username">Username</label>
<input id="username" name="username" autocomplete="username" autofocus>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password">
<button class="primary" type="submit">Sign in</button>
</form>
{banner}
</main>
</body>
</html>
"""

CONSOLE_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ProtoPi console</title>
<style>{style}</style>
</head>
<body data-csrf-header="{csrf_header}" data-csrf-token="{csrf_token}">
<main class="card">
<header>
<h1>PROTOPI CONSOLE</h1>
<span class="meta">{ssid} &middot; ap {access_point_state} &middot;
clients {station_count} &middot; timeout {timeout_seconds}s</span>
<form method="post" action="/logout"><button type="submit">Sign out</button></form>
</header>
<pre id="output">Type a command and press Enter. Arrow keys walk the history.
</pre>
<div id="cwd">{working_directory}</div>
<form class="prompt" id="prompt">
<input id="command" autocomplete="off" autocapitalize="off" spellcheck="false"
 placeholder="command" autofocus>
<button type="submit">Run</button>
</form>
</main>
<script>{script}</script>
</body>
</html>
"""

CONSOLE_SCRIPT = """
const outputPane = document.getElementById("output");
const commandInput = document.getElementById("command");
const promptForm = document.getElementById("prompt");
const workingDirectory = document.getElementById("cwd");
const csrfHeader = document.body.dataset.csrfHeader;
const csrfToken = document.body.dataset.csrfToken;
const history = [];
let historyIndex = 0;

function appendLine(text, className) {
  const line = document.createElement("span");
  if (className) { line.className = className; }
  line.textContent = text.endsWith("\\n") ? text : text + "\\n";
  outputPane.appendChild(line);
  outputPane.scrollTop = outputPane.scrollHeight;
}

async function runCommand(command) {
  appendLine("$ " + command, "echo");
  let response;
  try {
    response = await fetch("/run", {
      method: "POST",
      headers: { "Content-Type": "application/json", [csrfHeader]: csrfToken },
      body: JSON.stringify({ command: command })
    });
  } catch (error) {
    appendLine("Console unreachable: " + error, "exit-fail");
    return;
  }
  if (response.status === 401) {
    appendLine("Session expired. Reloading...", "exit-fail");
    window.location.reload();
    return;
  }
  const result = await response.json();
  if (result.error) {
    appendLine(result.error, "exit-fail");
    return;
  }
  if (result.output) { appendLine(result.output); }
  if (result.exit_code !== 0) {
    appendLine("[exit " + result.exit_code + "]", "exit-fail");
  }
  workingDirectory.textContent = result.working_directory;
}

promptForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const command = commandInput.value.trim();
  if (!command) { return; }
  if (command === "clear") {
    outputPane.textContent = "";
    commandInput.value = "";
    return;
  }
  history.push(command);
  historyIndex = history.length;
  commandInput.value = "";
  await runCommand(command);
  commandInput.focus();
});

commandInput.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowUp" && event.key !== "ArrowDown") { return; }
  if (history.length === 0) { return; }
  event.preventDefault();
  historyIndex += event.key === "ArrowUp" ? -1 : 1;
  historyIndex = Math.max(0, Math.min(history.length, historyIndex));
  commandInput.value = history[historyIndex] || "";
});
"""


if __name__ == "__main__":
    main()
