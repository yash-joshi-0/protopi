#!/usr/bin/env python3
ADMIN_USERNAME = "protogen"
ADMIN_PASSWORD = "change-me-before-use"

import hmac
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
from urllib.parse import urlparse

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
REQUEST_TIMEOUT_MS = 15000
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
WEB_ROOT = Path(__file__).resolve().parent / "web"
WEB_INDEX_NAME = "index.html"
WEB_VENDOR_NAME = "vendor"
DEFAULT_CONTENT_TYPE = "application/octet-stream"
WEB_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jsx": "text/jsx; charset=utf-8",
    ".svg": "image/svg+xml",
}
NO_STORE_CACHE_CONTROL = "no-store"
VENDOR_CACHE_CONTROL = "public, max-age=31536000, immutable"
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

    if not (WEB_ROOT / WEB_INDEX_NAME).is_file():
        raise SettingsError(f"The console page is missing from {WEB_ROOT}.")

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

    # Contract: Describe the session state the React console renders itself from.
    def session_payload(self, session: ConsoleSession | None) -> dict:
        if session is None:
            return {"authenticated": False, "ssid": ACCESS_POINT_SSID}

        return {
            "authenticated": True,
            "ssid": ACCESS_POINT_SSID,
            "csrf_token": session.csrf_token,
            "working_directory": session.working_directory,
            "access_point_active": self.access_point.active,
            "station_count": len(self.access_point.connected_stations()),
            "command_timeout_seconds": COMMAND_TIMEOUT_MS // 1000,
        }

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
    timeout = REQUEST_TIMEOUT_MS / 1000
    request_body = b""

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
            self.close_connection = True
            return b""

        try:
            return self.rfile.read(length)
        except OSError as error:
            print(f"Warning: could not read the request body ({error}).")
            self.close_connection = True
            return b""

    # Contract: Send a complete response with the given body, status, and headers.
    def send_body(
        self,
        body: bytes,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "text/html; charset=utf-8",
        extra_headers: List[tuple[str, str]] | None = None,
        cache_control: str = NO_STORE_CACHE_CONTROL,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")

        for name, value in extra_headers or []:
            self.send_header(name, value)

        self.end_headers()
        self.wfile.write(body)

    # Contract: Send a JSON payload to the client.
    def send_json(
        self,
        payload: dict,
        status: HTTPStatus = HTTPStatus.OK,
        extra_headers: List[tuple[str, str]] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_body(body, status, "application/json; charset=utf-8", extra_headers)

    # Contract: Send the plain text not found response.
    def send_not_found(self) -> None:
        self.send_body(b"Not found", HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")

    # Contract: Parse the body read for this request, or None when unreadable.
    def read_json_body(self) -> dict | None:
        try:
            parsed = json.loads(self.request_body.decode("utf-8", errors="replace"))
        except ValueError as error:
            print(f"Warning: unreadable JSON payload ({error}).")
            return None

        return parsed if isinstance(parsed, dict) else None

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

    # Contract: Serve the session state or a file from the web directory.
    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/session":
            session = self.server.get_session(self.read_session_token())
            self.send_json(self.server.session_payload(session))
            return

        self.send_web_file(path)

    # Contract: Serve one file from the web directory, or 404 when it is not there.
    def send_web_file(self, path: str) -> None:
        target = resolve_web_file(path)

        if target is None:
            self.send_not_found()
            return

        try:
            body = target.read_bytes()
        except OSError as error:
            print(f"Warning: could not read {target.name} ({error}).")
            self.send_not_found()
            return

        self.send_body(
            body,
            HTTPStatus.OK,
            content_type_for(target),
            cache_control=cache_control_for(target),
        )

    # Contract: Route the login, logout, and command endpoints.
    def do_POST(self) -> None:
        path = urlparse(self.path).path
        self.request_body = self.read_body()

        if path == "/login":
            self.handle_login()
        elif path == "/logout":
            self.handle_logout()
        elif path == "/run":
            self.handle_run()
        else:
            self.send_not_found()

    # Contract: Check submitted credentials and start a session when they match.
    def handle_login(self) -> None:
        if not self.server.login_allowed(self.remote_address):
            seconds = LOGIN_LOCKOUT_MS // 1000
            self.send_json(
                {"error": f"Too many attempts. Wait {seconds} seconds."},
                HTTPStatus.TOO_MANY_REQUESTS,
            )
            return

        request = self.read_json_body()

        if request is None:
            self.send_json({"error": "Malformed request."}, HTTPStatus.BAD_REQUEST)
            return

        username = str(request.get("username", ""))
        password = str(request.get("password", ""))

        if not self.server.credentials_match(username, password):
            self.server.record_failed_login(self.remote_address)
            self.send_json(
                {"error": "Incorrect username or password."}, HTTPStatus.UNAUTHORIZED
            )
            return

        session = self.server.create_session(self.remote_address)
        self.send_json(
            self.server.session_payload(session),
            extra_headers=[self.session_cookie_header(session.token)],
        )

    # Contract: End the current session and clear the cookie behind it.
    def handle_logout(self) -> None:
        self.server.end_session(self.read_session_token())
        self.send_json(
            self.server.session_payload(None),
            extra_headers=[self.session_cookie_header("", expire=True)],
        )

    # Contract: Run one submitted command for an authenticated session.
    def handle_run(self) -> None:
        session = self.server.get_session(self.read_session_token())

        if session is None:
            self.send_json({"error": "Session expired."}, HTTPStatus.UNAUTHORIZED)
            return

        if self.headers.get(CSRF_HEADER_NAME) != session.csrf_token:
            self.send_json({"error": "Bad request token."}, HTTPStatus.FORBIDDEN)
            return

        request = self.read_json_body()

        if request is None:
            self.send_json({"error": "Malformed request."}, HTTPStatus.BAD_REQUEST)
            return

        command = str(request.get("command", "")).strip()

        if not command:
            self.send_json({"error": "Empty command."}, HTTPStatus.BAD_REQUEST)
            return

        print(f"{self.remote_address} ran: {command}")
        self.send_json(self.server.run_command(session, command))


# Contract: Return the file under the web directory a request path names.
def resolve_web_file(path: str) -> Path | None:
    relative = path.lstrip("/") or WEB_INDEX_NAME
    candidate = (WEB_ROOT / relative).resolve()

    if not candidate.is_relative_to(WEB_ROOT):
        print(f"Warning: refused a request for {path} outside the web directory.")
        return None

    return candidate if candidate.is_file() else None


# Contract: Return the content type that follows from a served file's suffix.
def content_type_for(target: Path) -> str:
    return WEB_CONTENT_TYPES.get(target.suffix, DEFAULT_CONTENT_TYPE)


# Contract: Cache the pinned vendor libraries, but never the files you edit.
def cache_control_for(target: Path) -> str:
    if target.parent.name == WEB_VENDOR_NAME:
        return VENDOR_CACHE_CONTROL

    return NO_STORE_CACHE_CONTROL


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


if __name__ == "__main__":
    main()
