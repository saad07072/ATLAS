#!/usr/bin/env python3
"""
ATLAS Desktop Companion Launcher
Launches ATLAS Liquid-Glass Mini-HUD as an always-on-top floating desktop widget.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser() -> str | None:
    for path in [*EDGE_PATHS, *CHROME_PATHS]:
        if os.path.exists(path):
            return path
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("brave")


def is_server_ready(url: str = "http://localhost:3000") -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            return resp.status in (200, 304, 307, 308)
    except Exception:
        return False


def set_window_topmost(window_title_keyword: str = "ATLAS") -> bool:
    if sys.platform != "win32":
        return False

    ps_script = f"""
    Add-Type -TypeDefinition @"
    using System;
    using System.Runtime.InteropServices;
    public class Win32Top {{
        [DllImport("user32.dll")]
        public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    }}
    "@
    $p = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{window_title_keyword}*' }} | Select-Object -First 1
    if ($p -and $p.MainWindowHandle -ne 0) {{
        [Win32Top]::SetWindowPos($p.MainWindowHandle, [IntPtr](-1), 0, 0, 0, 0, 0x0001 -bor 0x0002)
        Write-Output "PINNED"
    }} else {{
        Write-Output "NOT_FOUND"
    }}
    """
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=4,
        )
        return "PINNED" in res.stdout
    except Exception:
        return False


def main() -> int:
    print("=" * 65)
    print("  ATLAS MARK VII // FLOATING LIQUID-GLASS DESKTOP COMPANION")
    print("=" * 65)

    browser = find_browser()
    if not browser:
        print("[ERROR] Neither Microsoft Edge nor Google Chrome was located on this system.")
        return 1

    target_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000/overlay"
    print(f"[*] Detected Browser Engine: {os.path.basename(browser)}")
    print(f"[*] Target Overlay Route:    {target_url}")

    if not is_server_ready():
        print("[*] ATLAS Next.js server not detected on http://localhost:3000.")
        print("[*] Launching frontend development server in background...")
        frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
        npm_cmd = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
        subprocess.Popen([npm_cmd, "run", "dev"], cwd=frontend_dir, shell=True)
        print("[*] Waiting for server to initialize...")
        for _ in range(12):
            time.sleep(1.0)
            if is_server_ready():
                print("[+] Server ready!")
                break

    # Launch standalone frameless app window
    launch_args = [
        browser,
        f"--app={target_url}",
        "--window-size=400,620",
        "--window-position=1480,380",
    ]
    print("[*] Summoning floating liquid-glass HUD companion...")
    proc = subprocess.Popen(launch_args)

    # Pin as Always-On-Top
    time.sleep(1.5)
    pinned = set_window_topmost("ATLAS")
    if pinned:
        print("[+] ATLAS Desktop Companion successfully pinned [ALWAYS ON TOP].")
    else:
        print("[+] ATLAS Desktop Companion active. (Toggle Mini-HUD mode anytime via Alt+M)")

    print("[*] Press Ctrl+C in this terminal to close companion.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\n[*] Companion closed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
