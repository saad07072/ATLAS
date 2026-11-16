from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CDP_PORTS = [9222, 9223, 9224]


def _encode_client_ws_frame(payload: bytes) -> bytes:
    """Encodes a masked RFC 6455 client text frame."""
    length = len(payload)
    header = bytearray([0x81])  # FIN + Text frame (0x1)
    mask = os.urandom(4)

    if length <= 125:
        header.append(0x80 | length)
    elif length <= 65535:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))

    header.extend(mask)
    masked_payload = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
    return bytes(header + masked_payload)


def _read_ws_frame(sock: socket.socket, timeout: float = 3.0) -> bytes:
    """Reads and unmasks a single RFC 6455 frame from the server."""
    sock.settimeout(timeout)

    header = sock.recv(2)
    if len(header) < 2:
        return b""

    byte2 = header[1]
    is_masked = bool(byte2 & 0x80)
    length = byte2 & 0x7F

    if length == 126:
        ext = sock.recv(2)
        if len(ext) < 2:
            return b""
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = sock.recv(8)
        if len(ext) < 8:
            return b""
        length = struct.unpack("!Q", ext)[0]

    mask = sock.recv(4) if is_masked else None

    # Read payload data
    chunks: list[bytes] = []
    bytes_read = 0
    while bytes_read < length:
        to_read = min(4096, length - bytes_read)
        chunk = sock.recv(to_read)
        if not chunk:
            break
        chunks.append(chunk)
        bytes_read += len(chunk)

    data = b"".join(chunks)
    if is_masked and mask:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return data


class BrowserCDPManager:
    """Manages deep browser control and introspection via Chrome DevTools Protocol (CDP)."""

    def __init__(self, ports: list[int] | None = None) -> None:
        self.candidate_ports = ports or list(DEFAULT_CDP_PORTS)
        self.active_port: int | None = None

    def find_active_endpoint(self) -> str | None:
        """Finds the first responsive CDP endpoint from the candidate port list."""
        for port in self.candidate_ports:
            endpoint = f"http://127.0.0.1:{port}"
            try:
                req = urllib.request.Request(f"{endpoint}/json/version", headers={"User-Agent": "ATLAS-CDP-Client"})
                with urllib.request.urlopen(req, timeout=0.8) as resp:
                    if resp.status == 200:
                        self.active_port = port
                        return endpoint
            except Exception:
                continue
        self.active_port = None
        return None

    def get_endpoint(self) -> str:
        """Returns the active or discovered endpoint, defaulting to port 9222."""
        endpoint = self.find_active_endpoint()
        if endpoint:
            return endpoint
        return f"http://127.0.0.1:{self.candidate_ports[0]}"

    def is_connected(self) -> bool:
        """Checks whether the browser CDP port is actively accessible."""
        return self.find_active_endpoint() is not None

    def get_version(self) -> dict[str, Any]:
        """Retrieves browser version, protocol version, and user agent via CDP."""
        endpoint = self.get_endpoint()
        try:
            req = urllib.request.Request(f"{endpoint}/json/version", headers={"User-Agent": "ATLAS-CDP-Client"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "connected": True,
                    "endpoint": endpoint,
                    "browser": data.get("Browser", "Unknown"),
                    "protocol_version": data.get("Protocol-Version", "1.3"),
                    "user_agent": data.get("User-Agent", ""),
                    "web_socket_debugger_url": data.get("webSocketDebuggerUrl"),
                }
        except Exception as exc:
            return {
                "connected": False,
                "endpoint": endpoint,
                "error": str(exc),
                "browser": "Unavailable",
            }

    def list_tabs(self) -> list[dict[str, Any]]:
        """Enumerates all open browser tabs (type 'page') via CDP /json/list."""
        endpoint = self.get_endpoint()
        try:
            req = urllib.request.Request(f"{endpoint}/json/list", headers={"User-Agent": "ATLAS-CDP-Client"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
                pages = []
                for t in targets:
                    if t.get("type") in {"page", "app"}:
                        pages.append(
                            {
                                "id": t.get("id", ""),
                                "title": t.get("title", "Untitled Tab"),
                                "url": t.get("url", ""),
                                "type": t.get("type", "page"),
                                "web_socket_debugger_url": t.get("webSocketDebuggerUrl"),
                                "frontend_url": t.get("devtoolsFrontendUrl"),
                            }
                        )
                return pages
        except Exception as exc:
            logger.debug("CDP list_tabs lookup failed: %s", exc)
            return []

    def open_tab(self, url: str) -> dict[str, Any]:
        """Opens a new tab via CDP /json/new?{url} and brings it into focus."""
        endpoint = self.get_endpoint()
        target_url = url if url.startswith("http://") or url.startswith("https://") else f"https://{url}"
        encoded_url = urllib.parse.quote(target_url, safe=":/?#[]@!$&'()*+,;=")
        try:
            req = urllib.request.Request(
                f"{endpoint}/json/new?{encoded_url}",
                headers={"User-Agent": "ATLAS-CDP-Client"},
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tab_id = data.get("id")
                if tab_id:
                    self.activate_tab(tab_id)
                return {
                    "success": True,
                    "id": tab_id,
                    "url": target_url,
                    "title": data.get("title", target_url),
                    "message": f"Opened new browser tab navigating to {target_url}.",
                }
        except Exception as exc:
            # Fallback to system default browser
            import webbrowser
            webbrowser.open(target_url)
            return {
                "success": True,
                "id": None,
                "url": target_url,
                "title": target_url,
                "message": f"Opened {target_url} via standard system browser.",
            }

    def activate_tab(self, tab_id: str) -> bool:
        """Brings the specified browser tab into focus/foreground."""
        endpoint = self.get_endpoint()
        try:
            req = urllib.request.Request(
                f"{endpoint}/json/activate/{tab_id}",
                headers={"User-Agent": "ATLAS-CDP-Client"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status in (200, 204)
        except Exception:
            # Some Chromium versions accept GET
            try:
                req_get = urllib.request.Request(
                    f"{endpoint}/json/activate/{tab_id}",
                    headers={"User-Agent": "ATLAS-CDP-Client"},
                )
                with urllib.request.urlopen(req_get, timeout=1.5) as resp:
                    return resp.status in (200, 204)
            except Exception as exc:
                logger.debug("Failed to activate tab %s: %s", tab_id, exc)
                return False

    def close_tab(self, tab_id: str) -> bool:
        """Closes the specified browser tab cleanly via CDP."""
        endpoint = self.get_endpoint()
        try:
            req = urllib.request.Request(
                f"{endpoint}/json/close/{tab_id}",
                headers={"User-Agent": "ATLAS-CDP-Client"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status in (200, 204)
        except Exception:
            try:
                req_get = urllib.request.Request(
                    f"{endpoint}/json/close/{tab_id}",
                    headers={"User-Agent": "ATLAS-CDP-Client"},
                )
                with urllib.request.urlopen(req_get, timeout=1.5) as resp:
                    return resp.status in (200, 204)
            except Exception as exc:
                logger.debug("Failed to close tab %s: %s", tab_id, exc)
                return False

    def close_tab_by_query(self, query: str) -> tuple[bool, str]:
        """Finds the best matching open tab by title or URL keyword and closes it."""
        tabs = self.list_tabs()
        if not tabs:
            return False, "No active browser tabs found via CDP protocol, sir."

        q = query.strip().lower()
        matched = None
        for t in tabs:
            title = t.get("title", "").lower()
            url = t.get("url", "").lower()
            if q in title or q in url:
                matched = t
                break

        if not matched and q in {"this tab", "current tab", "the tab", "active tab", "tab"}:
            matched = tabs[0]

        if matched:
            success = self.close_tab(matched["id"])
            if success:
                return True, f"Closed browser tab '{matched.get('title')}' ({matched.get('url')}), sir."
            return False, f"Attempted to close tab '{matched.get('title')}', but CDP returned non-200, sir."

        return False, f"Could not find a browser tab matching '{query}', sir."

    def send_cdp_command(
        self,
        web_socket_url: str,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 3.0,
    ) -> dict[str, Any]:
        """Executes a JSON-RPC CDP command over a direct WebSocket connection using pure standard library."""
        try:
            parsed = urllib.parse.urlparse(web_socket_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 9222
            path = parsed.path or "/"

            sock = socket.create_connection((host, port), timeout=timeout)
            key = base64.b64encode(os.urandom(16)).decode()
            handshake = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            sock.sendall(handshake.encode("ascii"))

            # Read handshake response
            resp_buf = bytearray()
            while b"\r\n\r\n" not in resp_buf:
                data = sock.recv(1024)
                if not data:
                    break
                resp_buf.extend(data)

            if b"101 " not in resp_buf:
                sock.close()
                return {"error": "WebSocket handshake failed"}

            # Send JSON-RPC Command
            call_id = 1
            cmd_body = json.dumps({"id": call_id, "method": method, "params": params or {}}).encode("utf-8")
            sock.sendall(_encode_client_ws_frame(cmd_body))

            # Read response frame
            raw_data = _read_ws_frame(sock, timeout=timeout)
            sock.close()

            if raw_data:
                return json.loads(raw_data.decode("utf-8", errors="ignore"))
            return {"status": "dispatched"}
        except Exception as exc:
            logger.debug("CDP WebSocket execution error (%s): %s", method, exc)
            return {"error": str(exc)}

    def reload_tab(self, tab_id: str | None = None) -> tuple[bool, str]:
        """Reloads/refreshes a browser tab."""
        tabs = self.list_tabs()
        if not tabs:
            return False, "No active browser tabs found via CDP protocol, sir."

        target = None
        if tab_id:
            for t in tabs:
                if t.get("id") == tab_id:
                    target = t
                    break
        else:
            target = tabs[0]

        if not target:
            return False, f"Browser tab '{tab_id}' was not found, sir."

        ws_url = target.get("web_socket_debugger_url")
        if ws_url:
            res = self.send_cdp_command(ws_url, "Page.reload", {"ignoreCache": True})
            if "error" not in res:
                return True, f"Reloaded browser tab '{target.get('title')}', sir."

        # Fallback: navigate tab to existing URL
        self.open_tab(target.get("url") or "about:blank")
        return True, f"Refreshed browser tab '{target.get('title')}', sir."

    def evaluate_expression(self, tab_id: str, expression: str) -> dict[str, Any]:
        """Evaluates JavaScript expression in the context of the target page."""
        tabs = self.list_tabs()
        target = next((t for t in tabs if t.get("id") == tab_id), None)
        if not target:
            return {"error": f"Tab {tab_id} not found"}

        ws_url = target.get("web_socket_debugger_url")
        if not ws_url:
            return {"error": "Tab has no WebSocket debugger URL"}

        return self.send_cdp_command(
            ws_url,
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )

    def launch_debug_browser(self, url: str | None = None, port: int = 9222) -> tuple[bool, str]:
        """Launches Google Chrome or Microsoft Edge with CDP remote debugging enabled."""
        target_url = url or "https://www.google.com"

        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            shutil.which("google-chrome") or "",
            shutil.which("chrome") or "",
            shutil.which("msedge") or "",
            shutil.which("chromium") or "",
        ]

        exe_path = next((p for p in chrome_paths if p and os.path.exists(p)), None)
        if not exe_path:
            # Fallback to standard open
            import webbrowser
            webbrowser.open(target_url)
            return True, f"Standard browser launched for {target_url} (debug executable path not found)."

        cmd = [
            exe_path,
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            target_url,
        ]

        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.active_port = port
            return True, f"Launched browser with CDP remote debugging active on port {port}, sir."
        except Exception as exc:
            return False, f"Failed to launch debug browser: {exc}"


browser_cdp_manager = BrowserCDPManager()
