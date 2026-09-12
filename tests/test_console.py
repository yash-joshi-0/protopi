#!/usr/bin/env python3
# Live-server checks for access_point.py so the console can be exercised off the Pi.
# Run from the repository root: python tests/test_console.py
from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Constants: These should not need to be changed.
REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_USERNAME = "protogen"
TEST_PASSWORD = "change-me-before-use"
WEB_FILES = [
    "/index.html",
    "/console.css",
    "/api.js",
    "/main.jsx",
    "/components/App.jsx",
    "/components/AdminPage.jsx",
    "/components/ChatForm.jsx",
    "/components/ChatPage.jsx",
    "/components/MessageList.jsx",
    "/components/LoginCard.jsx",
    "/components/ConsoleCard.jsx",
    "/components/ConsoleStatus.jsx",
    "/components/OutputPane.jsx",
    "/components/PromptForm.jsx",
    "/vendor/react.production.min.js",
    "/vendor/react-dom.production.min.js",
    "/vendor/babel.min.js",
]
APP_ROUTES = ("/", "/admin")
COMPONENT_NAMES = [
    "AdminPage",
    "App",
    "ChatForm",
    "ChatPage",
    "ConsoleCard",
    "ConsoleStatus",
    "LoginCard",
    "MessageList",
    "OutputPane",
    "PromptForm",
]
VENDOR_FILES = [
    "react.production.min.js",
    "react-dom.production.min.js",
    "babel.min.js",
]
TRAVERSAL_PATHS = [
    "/../access_point.py",
    "/vendor/../../access_point.py",
    "/./../../requirements.txt",
]
BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "chromium",
    "chromium-browser",
    "google-chrome",
]
BROWSER_TIMEOUT_MS = 60000
BROWSER_VIRTUAL_TIME_MS = 20000
SHORT_COMMAND_TIMEOUT_MS = 1500
ROOT_ELEMENT_MARKER = '<div id="root">'
JSX_COMPILE_SCRIPT = r"""
const fs = require("fs");
const Babel = require("./web/vendor/babel.min.js");
const files = ["web/main.jsx"].concat(
  fs.readdirSync("web/components").map((name) => "web/components/" + name)
);
for (const file of files) {
  try {
    Babel.transform(fs.readFileSync(file, "utf8"), { presets: ["react"] });
    console.log(file + " ok");
  } catch (error) {
    console.log(file + " " + error.message.split("\n")[0]);
  }
}
"""

sys.path.insert(0, str(REPO_ROOT))

import access_point


# Class: CheckRecorder prints each check as it runs and tracks the failures.
class CheckRecorder:
    def __init__(self) -> None:
        self.total = 0
        self.failures: List[str] = []

    # Contract: Record one check outcome and print it.
    def check(self, label: str, condition: Any, detail: str = "") -> None:
        self.total += 1
        passed = bool(condition)

        if not passed:
            self.failures.append(label)

        mark = "PASS" if passed else "FAIL"
        suffix = f"  {detail}" if detail else ""
        print(f"{mark}  {label}{suffix}")

    # Contract: Note a check that could not run in this environment.
    def skip(self, label: str, reason: str) -> None:
        print(f"SKIP  {label}  {reason}")

    # Contract: Print the tally and return the exit code for the process.
    def summary(self) -> int:
        print()
        print(f"{self.total - len(self.failures)}/{self.total} checks passed")

        for label in self.failures:
            print(f"  failed: {label}")

        return 1 if self.failures else 0


# Class: NoRedirect keeps urllib from following a response instead of reporting it.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# Class: ConsoleClient drives one running admin console over HTTP.
class ConsoleClient:
    # Contract: Remember the base address and start with no session cookie.
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.cookie = ""
        self.csrf_token = ""

    # Contract: Send one request and return the status, headers, and raw body.
    def request(
        self,
        path: str,
        payload: Dict[str, Any] | None = None,
        headers: Dict[str, str] | None = None,
        send_cookie: bool = True,
        raw_body: bytes | None = None,
    ) -> Tuple[int, Any, bytes]:
        request_headers = dict(headers or {})

        if send_cookie and self.cookie:
            request_headers["Cookie"] = self.cookie

        body = raw_body

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = urllib.request.Request(
            self.base + path, data=body, headers=request_headers
        )

        try:
            response = urllib.request.build_opener(NoRedirect).open(request)
            return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    # Contract: Send a request and return the status with the decoded JSON body.
    def json_request(self, path: str, payload=None, headers=None, send_cookie=True):
        status, response_headers, body = self.request(
            path, payload, headers, send_cookie
        )

        try:
            return status, json.loads(body.decode("utf-8")), response_headers
        except ValueError:
            return status, {}, response_headers

    # Contract: Sign in and remember the session cookie and request token.
    def sign_in(self, username: str = TEST_USERNAME, password: str = TEST_PASSWORD):
        status, payload, headers = self.json_request(
            "/login", {"username": username, "password": password}
        )

        if status == HTTPStatus.OK:
            self.cookie = headers.get("Set-Cookie", "").split(";")[0]
            self.csrf_token = payload.get("csrf_token", "")

        return status, payload, headers

    # Contract: Run one console command through the signed-in session.
    def run(self, command: str, token: str | None = None):
        status, payload, _ = self.json_request(
            "/run",
            {"command": command},
            {"X-ProtoPi-Token": self.csrf_token if token is None else token},
        )
        return status, payload


# Contract: Start an admin console on a free port and return the server and client.
def start_console(handler_class=None, chat_store=None):
    controller = access_point.AccessPointController()
    server = access_point.AdminConsoleServer(
        ("127.0.0.1", 0),
        handler_class or access_point.ConsoleRequestHandler,
        controller,
        chat_store or access_point.ChatStore(Path(tempfile.mkdtemp()) / "chat.db"),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, ConsoleClient(server.server_address[1])


# Contract: Stop a console started for one check group.
def stop_console(server) -> None:
    server.shutdown()
    server.server_close()


# Contract: Point the console at a usable shell, returning whether one was found.
def use_available_shell() -> bool:
    if Path(access_point.CONSOLE_SHELL).exists():
        return True

    found = shutil.which("bash")

    if found is None:
        return False

    access_point.CONSOLE_SHELL = found
    return True


# Contract: Return the first browser binary this machine has, or None.
def find_browser() -> str | None:
    for candidate in BROWSER_CANDIDATES:
        if Path(candidate).is_file():
            return candidate

        resolved = shutil.which(candidate)

        if resolved is not None:
            return resolved

    return None


# Contract: Check the shipped web directory holds every file the page asks for.
def check_web_files_present(recorder: CheckRecorder) -> None:
    for name in ["index.html", "console.css", "api.js", "main.jsx"]:
        target = access_point.WEB_ROOT / name
        recorder.check(f"web/{name} exists", target.is_file())

    for name in VENDOR_FILES:
        target = access_point.WEB_ROOT / "vendor" / name
        recorder.check(f"web/vendor/{name} exists", target.is_file())

    index = (access_point.WEB_ROOT / "index.html").read_text(encoding="utf-8")
    recorder.check("index.html loads the stylesheet", 'href="/console.css"' in index)
    recorder.check("index.html loads the api helpers", 'src="/api.js"' in index)
    recorder.check("index.html loads React", "react.production.min.js" in index)
    recorder.check("index.html loads ReactDOM", "react-dom.production.min.js" in index)
    recorder.check("index.html loads Babel", "babel.min.js" in index)
    recorder.check("index.html mounts the app last", index.rindex("main.jsx") > 0)

    for name in COMPONENT_NAMES:
        source_path = access_point.WEB_ROOT / "components" / f"{name}.jsx"
        recorder.check(f"components/{name}.jsx exists", source_path.is_file())

        if not source_path.is_file():
            continue

        source = source_path.read_text(encoding="utf-8")
        recorder.check(
            f"{name}.jsx declares its component",
            f"function {name}(" in source,
        )
        recorder.check(
            f"{name}.jsx is loaded by the page",
            f"/components/{name}.jsx" in index,
        )

    for name in COMPONENT_NAMES:
        script_tag = f'src="/components/{name}.jsx"'

        if name in ("App", "ConsoleCard"):
            continue

        recorder.check(
            f"{name}.jsx loads before its users",
            index.index(script_tag) < index.index('src="/components/App.jsx"'),
        )

    main = (access_point.WEB_ROOT / "main.jsx").read_text(encoding="utf-8")
    recorder.check("main.jsx mounts a React root", "ReactDOM.createRoot" in main)
    recorder.check("main.jsx renders the app", "<App />" in main)


# Contract: Check every JSX file compiles, naming the one that does not.
def check_jsx_compiles(recorder: CheckRecorder) -> None:
    node = shutil.which("node")

    if node is None:
        recorder.skip("jsx compiles", "node is not installed on this machine")
        return

    try:
        completed = subprocess.run(
            [node, "-e", JSX_COMPILE_SCRIPT],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=BROWSER_TIMEOUT_MS / 1000,
        )
    except (OSError, subprocess.SubprocessError) as error:
        recorder.check("jsx compiles", False, str(error))
        return

    for line in completed.stdout.splitlines():
        name, _, detail = line.partition(" ")
        recorder.check(f"{name} compiles", detail == "ok", detail)


# Contract: Check that settings which cannot work are refused before startup.
def check_settings_validation(recorder: CheckRecorder) -> None:
    originals = {
        "ACCESS_POINT_PASSPHRASE": access_point.ACCESS_POINT_PASSPHRASE,
        "ACCESS_POINT_SSID": access_point.ACCESS_POINT_SSID,
        "ACCESS_POINT_CHANNEL": access_point.ACCESS_POINT_CHANNEL,
        "CONSOLE_PORT": access_point.CONSOLE_PORT,
    }
    cases = {
        "short passphrase refused": ("ACCESS_POINT_PASSPHRASE", "short"),
        "empty ssid refused": ("ACCESS_POINT_SSID", ""),
        "bad channel refused": ("ACCESS_POINT_CHANNEL", 200),
        "bad port refused": ("CONSOLE_PORT", 70000),
    }

    for label, (name, value) in cases.items():
        setattr(access_point, name, value)

        try:
            access_point.validate_settings()
            refused = False
        except access_point.SettingsError:
            refused = True
        finally:
            setattr(access_point, name, originals[name])

        recorder.check(label, refused)

    try:
        access_point.validate_settings()
        accepted = True
    except access_point.SettingsError as error:
        accepted = False
        print(f"      unexpected: {error}")

    recorder.check("shipped settings validate", accepted)


# Contract: Check the hotspot profile nmcli would be given is the one we intend.
def check_profile_arguments(recorder: CheckRecorder) -> None:
    controller = access_point.AccessPointController()
    controller.nmcli_path = "nmcli"
    calls: List[List[str]] = []

    def record(arguments):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    controller.run_nmcli = record
    controller.create_profile()

    recorder.check("profile is created then modified", len(calls) == 2, f"{len(calls)}")

    if len(calls) != 2:
        return

    added = " ".join(calls[0])
    modified = " ".join(calls[1])

    recorder.check("profile binds the configured interface", "ifname wlan0" in added)
    recorder.check("profile does not autoconnect", "autoconnect no" in added)
    recorder.check("profile is an access point", "802-11-wireless.mode ap" in modified)
    recorder.check("profile uses wpa-psk", "wifi-sec.key-mgmt wpa-psk" in modified)
    recorder.check("profile disables pmf", "wifi-sec.pmf 1" in modified)
    recorder.check("profile shares ipv4", "ipv4.method shared" in modified)
    recorder.check(
        "profile serves the configured address", "192.168.4.1/24" in modified
    )

    controller.channel = 6
    recorder.check("channel 6 selects the 2.4GHz band", controller.band == "bg")
    controller.channel = 36
    recorder.check("channel 36 selects the 5GHz band", controller.band == "a")


# Contract: Check a missing nmcli leaves the console running instead of aborting.
def check_access_point_fallback(recorder: CheckRecorder) -> None:
    controller = access_point.AccessPointController()
    controller.nmcli_path = None
    started = controller.start()

    recorder.check("start reports failure without nmcli", started is False)
    recorder.check("controller stays inactive", controller.active is False)

    controller.shutdown()
    recorder.check("shutdown is safe when never started", controller.active is False)


# Contract: Check the static file routes serve the page and refuse escapes.
def check_static_serving(recorder: CheckRecorder) -> None:
    server, client = start_console()

    try:
        status, headers, body = client.request("/")
        recorder.check("/ serves the page", status == HTTPStatus.OK, f"{status}")
        recorder.check(
            "/ is served as html", "text/html" in headers.get("Content-Type", "")
        )
        recorder.check("/ is the index page", b'id="root"' in body)

        for path in WEB_FILES:
            status, headers, body = client.request(path)
            recorder.check(f"{path} serves", status == HTTPStatus.OK, f"{status}")
            recorder.check(f"{path} is not empty", len(body) > 0, f"{len(body)} bytes")

        status, headers, _ = client.request("/console.css")
        recorder.check(
            "css has its own content type",
            "text/css" in headers.get("Content-Type", ""),
            headers.get("Content-Type", ""),
        )

        status, headers, _ = client.request("/api.js")
        recorder.check(
            "js has its own content type",
            "javascript" in headers.get("Content-Type", ""),
            headers.get("Content-Type", ""),
        )

        status, headers, _ = client.request("/components/App.jsx")
        recorder.check(
            "jsx has its own content type",
            "jsx" in headers.get("Content-Type", ""),
            headers.get("Content-Type", ""),
        )

        status, headers, _ = client.request("/vendor/babel.min.js")
        recorder.check(
            "vendor files are cached",
            "max-age" in headers.get("Cache-Control", ""),
            headers.get("Cache-Control", ""),
        )

        status, headers, _ = client.request("/components/App.jsx")
        recorder.check(
            "edited files are never cached",
            headers.get("Cache-Control", "") == access_point.NO_STORE_CACHE_CONTROL,
            headers.get("Cache-Control", ""),
        )

        for path in TRAVERSAL_PATHS:
            status, _, body = client.request(path)
            recorder.check(
                f"traversal refused: {path}",
                status == HTTPStatus.NOT_FOUND,
                f"{status}",
            )
            recorder.check(f"no source leaked: {path}", b"ADMIN_PASSWORD" not in body)

        status, _, _ = client.request("/does-not-exist.js")
        recorder.check("missing file is 404", status == HTTPStatus.NOT_FOUND)

        recorder.check(
            "resolver refuses paths outside the web directory",
            access_point.resolve_web_file("/../access_point.py") is None,
        )
        recorder.check(
            "resolver finds the index page",
            access_point.resolve_web_file("/") is not None,
        )
    finally:
        stop_console(server)


# Contract: Check the session, login, and logout endpoints behave as the app expects.
def check_session_api(recorder: CheckRecorder) -> None:
    server, client = start_console()

    try:
        status, payload, _ = client.json_request("/api/session")
        recorder.check("anonymous session reports no login", status == HTTPStatus.OK)
        recorder.check(
            "anonymous session is unauthenticated",
            payload.get("authenticated") is False,
        )
        recorder.check("anonymous session leaks no token", "csrf_token" not in payload)

        status, payload, headers = client.sign_in(password="wrong")
        recorder.check(
            "bad password is rejected", status == HTTPStatus.UNAUTHORIZED, f"{status}"
        )
        recorder.check("bad password sets no cookie", headers.get("Set-Cookie") is None)
        recorder.check("bad password explains itself", "error" in payload)

        status, payload, headers = client.sign_in(username="wrong")
        recorder.check(
            "bad username is rejected", status == HTTPStatus.UNAUTHORIZED, f"{status}"
        )

        status, payload, headers = client.sign_in()
        recorder.check("good login succeeds", status == HTTPStatus.OK, f"{status}")
        recorder.check("good login authenticates", payload.get("authenticated") is True)
        recorder.check("good login returns a token", len(client.csrf_token) > 20)
        recorder.check(
            "cookie is http only", "HttpOnly" in headers.get("Set-Cookie", "")
        )
        recorder.check(
            "cookie is same site strict",
            "SameSite=Strict" in headers.get("Set-Cookie", ""),
        )
        recorder.check(
            "login reports the console state",
            "working_directory" in payload and "command_timeout_seconds" in payload,
        )

        status, payload, _ = client.json_request("/api/session")
        recorder.check("session survives on the cookie", payload.get("authenticated"))
        recorder.check(
            "session returns the same token",
            payload.get("csrf_token") == client.csrf_token,
        )

        status, payload, headers = client.json_request("/logout", {})
        recorder.check("logout succeeds", status == HTTPStatus.OK, f"{status}")
        recorder.check(
            "logout clears the cookie", "Max-Age=0" in headers.get("Set-Cookie", "")
        )

        status, payload, _ = client.json_request("/api/session")
        recorder.check(
            "session is gone after logout", payload.get("authenticated") is False
        )
    finally:
        stop_console(server)


# Contract: Check that an unauthenticated or forged request cannot run commands.
def check_command_guards(recorder: CheckRecorder) -> None:
    server, client = start_console()

    try:
        status, payload = client.run("echo nope")
        recorder.check(
            "command without a session is refused",
            status == HTTPStatus.UNAUTHORIZED,
            f"{status}",
        )

        client.sign_in()
        status, payload = client.run("echo nope", token="forged")
        recorder.check(
            "command with a bad token is refused",
            status == HTTPStatus.FORBIDDEN,
            f"{status}",
        )

        status, _, _ = client.request(
            "/run", headers={"X-ProtoPi-Token": client.csrf_token}, raw_body=b""
        )
        recorder.check(
            "empty command body is refused",
            status == HTTPStatus.BAD_REQUEST,
            f"{status}",
        )

        status, payload, _ = client.json_request(
            "/run", {"command": "   "}, {"X-ProtoPi-Token": client.csrf_token}
        )
        recorder.check(
            "blank command is refused", status == HTTPStatus.BAD_REQUEST, f"{status}"
        )

        oversized = b'{"filler":"' + b"a" * access_point.MAXIMUM_REQUEST_BYTES + b'"}'
        status, _, _ = client.request("/login", raw_body=oversized)
        recorder.check(
            "oversized body is refused", status == HTTPStatus.BAD_REQUEST, f"{status}"
        )

        status, _, _ = client.request("/nowhere", {})
        recorder.check(
            "unknown endpoint is 404", status == HTTPStatus.NOT_FOUND, f"{status}"
        )
    finally:
        stop_console(server)


# Contract: Check every endpoint leaves a kept-alive connection usable afterwards.
def check_connection_reuse(recorder: CheckRecorder) -> None:
    server, client = start_console()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])

    # Contract: Send one request down the shared connection and return it.
    def send(method, path, body=None, headers=None):
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()

    try:
        credentials = json.dumps({"username": TEST_USERNAME, "password": TEST_PASSWORD})
        connection.request(
            "POST",
            "/login",
            body=credentials,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        cookie = (response.getheader("Set-Cookie") or "").split(";")[0]
        payload = json.loads(response.read())
        token = payload.get("csrf_token", "")
        signed_headers = {"Cookie": cookie, "Content-Type": "application/json"}
        command_headers = dict(signed_headers, **{"X-ProtoPi-Token": token})

        status, body = send("GET", "/api/session", headers={"Cookie": cookie})
        recorder.check(
            "session reuses the login connection", status == 200, f"{status}"
        )

        status, body = send(
            "POST", "/run", json.dumps({"command": "echo reuse"}), command_headers
        )
        recorder.check("run reuses the connection", status == 200, f"{status}")

        status, body = send("GET", "/api/session", headers={"Cookie": cookie})
        recorder.check("session survives a run", status == 200, f"{status}")

        status, body = send("POST", "/logout", json.dumps({}), signed_headers)
        recorder.check("logout reuses the connection", status == 200, f"{status}")

        status, body = send("GET", "/api/session", headers={"Cookie": cookie})
        recorder.check(
            "session survives a logout", status == 200, f"{status} {body[:40]}"
        )
        recorder.check(
            "session after logout is still json",
            body.startswith(b"{"),
            repr(body[:60]),
        )
    except (OSError, http.client.HTTPException, ValueError) as error:
        recorder.check("connection stays usable", False, f"{type(error).__name__}")
    finally:
        connection.close()
        stop_console(server)


# Contract: Check the chat stores messages, reads them back, and refuses bad input.
def check_chat_api(recorder: CheckRecorder) -> None:
    database = Path(tempfile.mkdtemp()) / "chat.db"
    store = access_point.ChatStore(database)
    server, client = start_console(chat_store=store)

    try:
        status, payload, _ = client.json_request("/api/messages")
        recorder.check("chat starts empty", payload.get("messages") == [], f"{status}")
        recorder.check(
            "chat reports the limits it enforces",
            payload.get("maximum_username_length")
            == access_point.MAXIMUM_USERNAME_LENGTH,
        )

        status, payload, _ = client.json_request(
            "/api/messages", {"username": "Kade", "body": "hello suit"}
        )
        recorder.check(
            "a message is accepted", status == HTTPStatus.CREATED, f"{status}"
        )
        message = payload.get("message", {})
        recorder.check(
            "the stored message comes back", message.get("body") == "hello suit"
        )
        recorder.check(
            "the message is timed", isinstance(message.get("sent_at_ms"), int)
        )

        client.json_request("/api/messages", {"username": "Vex", "body": "boop"})
        status, payload, _ = client.json_request("/api/messages")
        stored = payload.get("messages", [])
        recorder.check("both messages are stored", len(stored) == 2, f"{len(stored)}")
        recorder.check(
            "messages come back oldest first",
            [item["body"] for item in stored] == ["hello suit", "boop"],
        )
        recorder.check("messages keep their sender", stored[1]["username"] == "Vex")

        refusals = {
            "a blank message is refused": {"username": "Kade", "body": "   "},
            "a blank username is refused": {"username": "", "body": "hi"},
            "a long username is refused": {
                "username": "z" * (access_point.MAXIMUM_USERNAME_LENGTH + 1),
                "body": "hi",
            },
            "a long message is refused": {
                "username": "Kade",
                "body": "z" * (access_point.MAXIMUM_MESSAGE_LENGTH + 1),
            },
        }

        for label, payload_body in refusals.items():
            status, payload, _ = client.json_request("/api/messages", payload_body)
            recorder.check(label, status == HTTPStatus.BAD_REQUEST, f"{status}")

        status, payload, _ = client.json_request("/api/messages")
        recorder.check(
            "refused messages are not stored", len(payload.get("messages", [])) == 2
        )

        recorder.check(
            "the chat needs no login",
            "csrf_token" not in payload and payload.get("messages") is not None,
        )
    finally:
        stop_console(server)

    reopened = access_point.ChatStore(database)
    recorder.check("messages survive a restart", len(reopened.recent_messages()) == 2)
    recorder.check(
        "the history is capped",
        len(reopened.recent_messages(limit=1)) == 1,
    )


# Contract: Check the chat and the admin console answer on their own routes.
def check_page_routes(recorder: CheckRecorder) -> None:
    server, client = start_console()

    try:
        for path in APP_ROUTES:
            status, headers, body = client.request(path)
            recorder.check(
                f"{path} serves the page", status == HTTPStatus.OK, f"{status}"
            )
            recorder.check(f"{path} is the app shell", b'id="root"' in body)
            recorder.check(
                f"{path} is served as html",
                "text/html" in headers.get("Content-Type", ""),
            )

        status, _, _ = client.request("/admin/nope")
        recorder.check("an unknown route is still 404", status == HTTPStatus.NOT_FOUND)

        app_source = (access_point.WEB_ROOT / "components" / "App.jsx").read_text(
            encoding="utf-8"
        )
        recorder.check("the router knows the admin path", '"/admin"' in app_source)
        recorder.check("the router falls back to the chat", "ChatPage" in app_source)
    finally:
        stop_console(server)


# Contract: Check repeated bad logins lock a client out instead of allowing guessing.
def check_login_lockout(recorder: CheckRecorder) -> None:
    server, client = start_console()

    try:
        statuses = []

        for _ in range(access_point.LOGIN_ATTEMPT_LIMIT + 1):
            status, _, _ = client.sign_in(password="wrong")
            statuses.append(status)

        recorder.check(
            "guessing ends in a lockout",
            statuses[-1] == HTTPStatus.TOO_MANY_REQUESTS,
            f"{statuses}",
        )

        status, _, _ = client.sign_in()
        recorder.check(
            "lockout blocks the right password too",
            status == HTTPStatus.TOO_MANY_REQUESTS,
            f"{status}",
        )
    finally:
        stop_console(server)


# Contract: Check commands run, keep their directory, and report failures.
def check_command_execution(recorder: CheckRecorder) -> None:
    if not use_available_shell():
        recorder.skip("command execution", "no shell available on this machine")
        return

    server, client = start_console()

    try:
        client.sign_in()

        status, payload = client.run("echo hello from protopi")
        recorder.check("command runs", status == HTTPStatus.OK, f"{status}")
        recorder.check(
            "command output comes back",
            "hello from protopi" in payload.get("output", ""),
            repr(payload.get("output")),
        )
        recorder.check("successful command exits zero", payload.get("exit_code") == 0)

        status, payload = client.run("cd /tmp")
        recorder.check(
            "cd changes the reported directory",
            payload.get("working_directory") == "/tmp",
            payload.get("working_directory", ""),
        )

        status, payload = client.run("pwd")
        recorder.check(
            "directory carries to the next command",
            payload.get("output", "").strip() == "/tmp",
            repr(payload.get("output")),
        )

        status, payload = client.run("exit 3")
        recorder.check("exit code is reported", payload.get("exit_code") == 3)
        recorder.check(
            "directory survives a failed command",
            payload.get("working_directory") == "/tmp",
        )

        status, payload = client.run("nosuchcommand")
        recorder.check(
            "stderr comes back", "not found" in payload.get("output", "").lower()
        )
        recorder.check("missing command exits nonzero", payload.get("exit_code") != 0)

        original_timeout = access_point.COMMAND_TIMEOUT_MS
        access_point.COMMAND_TIMEOUT_MS = SHORT_COMMAND_TIMEOUT_MS

        try:
            status, payload = client.run("sleep 30")
        finally:
            access_point.COMMAND_TIMEOUT_MS = original_timeout

        recorder.check(
            "a hung command is killed",
            payload.get("exit_code") == 124,
            f"{payload.get('exit_code')}",
        )
        recorder.check(
            "timeout is explained", "timed out" in payload.get("output", "").lower()
        )
    finally:
        stop_console(server)


# Contract: Check the React app renders the login card and the console in a browser.
def check_browser_render(recorder: CheckRecorder) -> None:
    browser = find_browser()

    if browser is None:
        recorder.skip("browser render", "no Chromium based browser found")
        return

    database = Path(tempfile.mkdtemp()) / "chat.db"
    store = access_point.ChatStore(database)
    store.add_message("Vex", "stored before the browser opened")
    server, client = start_console(build_autologin_handler(), store)

    try:
        chat_root = extract_root(render_page(browser, f"{client.base}/"))
        recorder.check("React renders the chat on /", "PROTOPI CHAT" in chat_root)
        recorder.check("the chat shows its form", "chat-form" in chat_root)
        recorder.check(
            "the chat shows a stored message",
            "stored before the browser opened" in chat_root,
        )
        recorder.check("the chat names the sender", "Vex" in chat_root)
        recorder.check("the chat links to the console", 'href="/admin"' in chat_root)
        recorder.check(
            "the chat is not the login card", "PROTOPI ADMIN" not in chat_root
        )

        login_root = extract_root(render_page(browser, f"{client.base}/admin"))
        recorder.check(
            "React renders the login card on /admin", "PROTOPI ADMIN" in login_root
        )
        recorder.check(
            "login card asks for a password", 'type="password"' in login_root
        )
        recorder.check("the login card is not the chat", "chat-form" not in login_root)

        console_root = extract_root(render_page(browser, f"{client.base}/auto-login"))
        recorder.check(
            "React renders the console after login", "PROTOPI CONSOLE" in console_root
        )
        recorder.check("console shows a prompt", 'class="prompt"' in console_root)
    finally:
        stop_console(server)


# Contract: Return what React rendered into the root element, ignoring the scripts.
def extract_root(dom: str | None) -> str:
    if dom is None:
        return ""

    opening = dom.find(ROOT_ELEMENT_MARKER)

    if opening < 0:
        return ""

    start = opening + len(ROOT_ELEMENT_MARKER)
    end = dom.find("<script", start)
    return dom[start:end] if end > start else dom[start:]


# Contract: Build a handler that signs itself in, for driving the app in a browser.
def build_autologin_handler():
    page = (
        "<!doctype html><meta charset='utf-8'><body><script>"
        "fetch('/login', {method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        f"body: JSON.stringify({{username:'{TEST_USERNAME}',"
        f"password:'{TEST_PASSWORD}'}})"
        "}).then(() => { window.location = '/admin'; });"
        "</script></body>"
    ).encode("utf-8")

    # Class: AutoLoginHandler adds a page that signs in before showing the console.
    class AutoLoginHandler(access_point.ConsoleRequestHandler):
        # Contract: Serve the sign-in helper, or fall back to the console routes.
        def do_GET(self) -> None:
            if self.path == "/auto-login":
                self.send_body(page, HTTPStatus.OK, "text/html; charset=utf-8")
                return

            super().do_GET()

    return AutoLoginHandler


# Contract: Load one page in a headless browser and return the rendered DOM.
def render_page(browser: str, url: str) -> str | None:
    profile = Path(tempfile.mkdtemp())

    try:
        completed = subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--virtual-time-budget={BROWSER_VIRTUAL_TIME_MS}",
                f"--user-data-dir={profile}",
                "--dump-dom",
                url,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=BROWSER_TIMEOUT_MS / 1000,
        )
    except (OSError, subprocess.SubprocessError) as error:
        print(f"      browser failed: {error}")
        return None
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    return completed.stdout


# Contract: Run every check group and return the exit code for the process.
def main() -> int:
    recorder = CheckRecorder()
    check_web_files_present(recorder)
    check_jsx_compiles(recorder)
    check_settings_validation(recorder)
    check_profile_arguments(recorder)
    check_access_point_fallback(recorder)
    check_static_serving(recorder)
    check_session_api(recorder)
    check_command_guards(recorder)
    check_chat_api(recorder)
    check_page_routes(recorder)
    check_connection_reuse(recorder)
    check_login_lockout(recorder)
    check_command_execution(recorder)
    check_browser_render(recorder)
    return recorder.summary()


if __name__ == "__main__":
    sys.exit(main())
