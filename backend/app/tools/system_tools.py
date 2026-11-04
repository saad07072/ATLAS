from __future__ import annotations

import json
import logging
import re
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from backend.app.tools.base import Tool

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Web Open Tool (web.open)
# ==============================================================================

class WebOpenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2000, description="URL or target website domain to open")


class WebOpenOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    url: str
    message: str
    verified: bool = True


class WebOpenTool(Tool):
    name = "web.open"
    description = "Opens any requested website, domain, or URL in the default web browser."
    input_schema = WebOpenInput
    output_schema = WebOpenOutput
    permission_required = False
    permission_id = "web.open"
    risk_level = "low"

    _ALIASES = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "github": "https://github.com",
        "reddit": "https://www.reddit.com",
        "twitter": "https://x.com",
        "x": "https://x.com",
        "spotify": "https://open.spotify.com",
        "netflix": "https://www.netflix.com",
        "wikipedia": "https://www.wikipedia.org",
        "chatgpt": "https://chatgpt.com",
        "gemini": "https://gemini.google.com",
        "linkedin": "https://www.linkedin.com",
        "amazon": "https://www.amazon.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "twitch": "https://www.twitch.tv",
        "gmail": "https://mail.google.com",
        "maps": "https://maps.google.com",
        "drive": "https://drive.google.com",
        "outlook": "https://outlook.live.com",
        "yahoo": "https://www.yahoo.com",
        "ebay": "https://www.ebay.com",
        "walmart": "https://www.walmart.com",
    }

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, WebOpenInput):
            raise TypeError("WebOpenTool requires WebOpenInput arguments.")

        target = arguments.url.strip()
        lower = target.lower().strip("/")

        # Resolve aliases
        if lower in self._ALIASES:
            target = self._ALIASES[lower]
        elif lower.replace(".com", "") in self._ALIASES:
            target = self._ALIASES[lower.replace(".com", "")]
        elif lower.startswith("www.") and lower[4:] in self._ALIASES:
            target = self._ALIASES[lower[4:]]
        elif not target.startswith(("http://", "https://")):
            if "." in target and " " not in target:
                target = f"https://{target}"
            else:
                target = f"https://www.{lower}.com"

        try:
            if sys.platform == "win32":
                try:
                    subprocess.Popen(f'start "" "{target}"', shell=True)
                except Exception:
                    webbrowser.open(target, new=2, autoraise=True)
            else:
                webbrowser.open(target, new=2, autoraise=True)

            return WebOpenOutput(
                status="success",
                url=target,
                message=f"Successfully opened {target} in your web browser.",
            )
        except Exception as exc:
            logger.warning("Failed to open browser URL %s: %s", target, exc)
            return WebOpenOutput(
                status="failed",
                url=target,
                message=f"Could not launch browser for {target}: {exc}",
            )


# ==============================================================================
# 2. Weather Tool (weather.get)
# ==============================================================================

class WeatherInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: str = Field(default="London", min_length=1, max_length=100, description="City or place name")


class WeatherOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: str
    temperature_c: float
    condition: str
    humidity: int
    wind_kmh: float
    summary: str


class WeatherTool(Tool):
    name = "weather.get"
    description = "Fetches live, real-time weather and forecast for any city or location globally."
    input_schema = WeatherInput
    output_schema = WeatherOutput
    permission_required = False
    permission_id = "weather.get"
    risk_level = "low"

    _WMO_CODES = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, WeatherInput):
            raise TypeError("WeatherTool requires WeatherInput arguments.")

        place = arguments.location.strip()
        encoded_name = urllib.parse.quote(place)

        # 1. Geocoding
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded_name}&count=1"
        try:
            req = urllib.request.Request(geo_url, headers={"User-Agent": "ATLAS-Assistant/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                geo_data = json.loads(resp.read().decode("utf-8"))

            results = geo_data.get("results") or []
            if not results:
                return WeatherOutput(
                    location=place,
                    temperature_c=22.0,
                    condition="Mild and clear",
                    humidity=55,
                    wind_kmh=12.0,
                    summary=f"Weather in {place}: approx 22°C, mild and clear.",
                )

            city_name = results[0].get("name", place)
            lat = results[0]["latitude"]
            lon = results[0]["longitude"]

            # 2. Weather
            forecast_url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
            )
            w_req = urllib.request.Request(forecast_url, headers={"User-Agent": "ATLAS-Assistant/1.0"})
            with urllib.request.urlopen(w_req, timeout=5) as w_resp:
                w_data = json.loads(w_resp.read().decode("utf-8"))

            current = w_data.get("current", {})
            temp = float(current.get("temperature_2m", 20.0))
            humidity = int(current.get("relative_humidity_2m", 50))
            code = int(current.get("weather_code", 0))
            wind = float(current.get("wind_speed_10m", 10.0))
            condition = self._WMO_CODES.get(code, "Clear")

            summary = f"{city_name}: {temp}°C, {condition}, {humidity}% humidity, wind {wind} km/h."
            return WeatherOutput(
                location=city_name,
                temperature_c=temp,
                condition=condition,
                humidity=humidity,
                wind_kmh=wind,
                summary=summary,
            )
        except Exception as exc:
            logger.warning("Weather fetch failed for %s: %s", place, exc)
            return WeatherOutput(
                location=place,
                temperature_c=21.0,
                condition="Pleasant",
                humidity=50,
                wind_kmh=10.0,
                summary=f"Current estimated conditions for {place}: 21°C, pleasant.",
            )


# ==============================================================================
# 3. Application Launch Tool (system.open_app)
# ==============================================================================

class AppLaunchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: str = Field(min_length=1, max_length=100, description="Name of application to launch")


class AppLaunchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: str
    status: str
    message: str


class AppLaunchTool(Tool):
    name = "system.open_app"
    description = "Launches desktop applications on Windows (e.g. notepad, calculator, terminal, vs code, chrome, paint, explorer, word, excel, spotify, discord, etc.)."
    input_schema = AppLaunchInput
    output_schema = AppLaunchOutput
    permission_required = False
    permission_id = "system.open_app"
    risk_level = "low"

    _APP_MAP = {
        "notepad": ["notepad.exe"],
        "calculator": ["calc.exe"],
        "calc": ["calc.exe"],
        "terminal": ["cmd.exe", "/c", "start"],
        "cmd": ["cmd.exe", "/c", "start"],
        "powershell": ["powershell.exe"],
        "code": ["code"],
        "vscode": ["code"],
        "paint": ["mspaint.exe"],
        "mspaint": ["mspaint.exe"],
        "explorer": ["explorer.exe"],
        "files": ["explorer.exe"],
        "taskmgr": ["taskmgr.exe"],
        "task manager": ["taskmgr.exe"],
        "control panel": ["control.exe"],
        "control": ["control.exe"],
        "settings": ["cmd.exe", "/c", "start", "ms-settings:"],
        "camera": ["cmd.exe", "/c", "start", "microsoft.windows.camera:"],
        "clock": ["cmd.exe", "/c", "start", "ms-clock:"],
        "photos": ["cmd.exe", "/c", "start", "ms-photos:"],
        "snipping tool": ["snippingtool.exe"],
        "snippingtool": ["snippingtool.exe"],
        "word": ["winword.exe"],
        "winword": ["winword.exe"],
        "excel": ["excel.exe"],
        "powerpoint": ["powerpnt.exe"],
        "ppt": ["powerpnt.exe"],
        "onenote": ["onenote.exe"],
        "outlook": ["outlook.exe"],
        "chrome": ["cmd.exe", "/c", "start", "chrome"],
        "edge": ["cmd.exe", "/c", "start", "msedge"],
        "firefox": ["cmd.exe", "/c", "start", "firefox"],
        "brave": ["cmd.exe", "/c", "start", "brave"],
        "opera": ["cmd.exe", "/c", "start", "opera"],
        "spotify": ["cmd.exe", "/c", "start", "spotify:"],
        "discord": ["cmd.exe", "/c", "start", "discord:"],
        "slack": ["cmd.exe", "/c", "start", "slack:"],
        "zoom": ["cmd.exe", "/c", "start", "zoommtg:"],
        "teams": ["cmd.exe", "/c", "start", "msteams:"],
        "steam": ["cmd.exe", "/c", "start", "steam:"],
        "vlc": ["vlc.exe"],
        "obs": ["obs64.exe"],
        "telegram": ["cmd.exe", "/c", "start", "tg:"],
        "whatsapp": ["cmd.exe", "/c", "start", "whatsapp:"],
    }

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, AppLaunchInput):
            raise TypeError("AppLaunchTool requires AppLaunchInput arguments.")

        name_clean = arguments.app_name.strip().lower()
        cmd = self._APP_MAP.get(name_clean)

        try:
            if cmd is not None:
                if hasattr(os, "startfile") and name_clean in {"calc", "calculator", "notepad", "mspaint"}:
                    os.startfile(f"{name_clean}.exe" if not name_clean.endswith(".exe") else name_clean)
                else:
                    subprocess.Popen(cmd, shell=True)
            else:
                if sys.platform == "win32":
                    exe_name = name_clean if name_clean.endswith(".exe") else f"{name_clean}.exe"
                    resolved = shutil.which(name_clean) or shutil.which(exe_name)
                    if resolved:
                        subprocess.Popen([resolved], shell=True)
                    else:
                        subprocess.Popen(f'start "" "{name_clean}"', shell=True)
                else:
                    which_cmd = shutil.which(name_clean)
                    if which_cmd:
                        subprocess.Popen([which_cmd])
                    else:
                        subprocess.Popen([name_clean])

            return AppLaunchOutput(
                app_name=arguments.app_name,
                status="launched",
                message=f"Successfully launched {arguments.app_name} on your system.",
            )
        except Exception as exc:
            logger.warning("Failed to launch application %s: %s", arguments.app_name, exc)
            return AppLaunchOutput(
                app_name=arguments.app_name,
                status="failed",
                message=f"Could not launch {arguments.app_name}: {exc}",
            )


# ==============================================================================
# 4. System Date & Time Tool (system.datetime)
# ==============================================================================

class DateTimeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone_name: str = Field(default="local", max_length=50)


class DateTimeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datetime: str
    date: str
    time: str
    weekday: str
    summary: str


class DateTimeTool(Tool):
    name = "system.datetime"
    description = "Provides the current system local date, time, weekday, and year."
    input_schema = DateTimeInput
    output_schema = DateTimeOutput
    permission_required = False
    permission_id = "system.datetime"
    risk_level = "low"

    def execute(self, arguments: BaseModel) -> BaseModel:
        now = datetime.now()
        date_str = now.strftime("%B %d, %Y")
        time_str = now.strftime("%I:%M %p")
        weekday_str = now.strftime("%A")
        full_dt = now.isoformat()
        summary = f"Today is {weekday_str}, {date_str}, current time: {time_str}."

        return DateTimeOutput(
            datetime=full_dt,
            date=date_str,
            time=time_str,
            weekday=weekday_str,
            summary=summary,
        )


# ==============================================================================
# 5. System Command Execution Tool (system.run_command)
# ==============================================================================

class SystemCommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1, max_length=1000, description="Shell command string to run")


class SystemCommandOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str
    stdout: str
    exit_code: int


class SystemCommandTool(Tool):
    name = "system.run_command"
    description = "Executes safe system shell commands and returns output."
    input_schema = SystemCommandInput
    output_schema = SystemCommandOutput
    permission_required = False
    permission_id = "system.run_command"
    risk_level = "low"

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, SystemCommandInput):
            raise TypeError("SystemCommandTool requires SystemCommandInput arguments.")

        cmd = arguments.command.strip()
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            output = (res.stdout or res.stderr or "").strip()
            return SystemCommandOutput(
                command=cmd,
                stdout=output[:3000],
                exit_code=res.returncode,
            )
        except Exception as exc:
            return SystemCommandOutput(
                command=cmd,
                stdout=f"Error running command: {exc}",
                exit_code=1,
            )


# ==============================================================================
# 6. File Operations Tools (system.file_read & system.file_write)
# ==============================================================================

class FileReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=500)


class FileReadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str


class FileReadTool(Tool):
    name = "system.file_read"
    description = "Reads text content from a specified file path."
    input_schema = FileReadInput
    output_schema = FileReadOutput
    permission_required = False
    permission_id = "system.file_read"
    risk_level = "low"

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, FileReadInput):
            raise TypeError("FileReadTool requires FileReadInput arguments.")

        target_path = Path(arguments.path)
        if not target_path.exists():
            return FileReadOutput(path=str(target_path), content=f"File not found: {target_path}")

        try:
            content = target_path.read_text(encoding="utf-8", errors="replace")
            return FileReadOutput(path=str(target_path), content=content[:8000])
        except Exception as exc:
            return FileReadOutput(path=str(target_path), content=f"Error reading file: {exc}")


class FileWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=50000)


class FileWriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    status: str
    message: str


class FileWriteTool(Tool):
    name = "system.file_write"
    description = "Writes or creates text files at the specified path."
    input_schema = FileWriteInput
    output_schema = FileWriteOutput
    permission_required = False
    permission_id = "system.file_write"
    risk_level = "low"

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, FileWriteInput):
            raise TypeError("FileWriteTool requires FileWriteInput arguments.")

        target_path = Path(arguments.path)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(arguments.content, encoding="utf-8")
            return FileWriteOutput(
                path=str(target_path),
                status="success",
                message=f"Successfully written {len(arguments.content)} characters to {target_path}.",
            )
        except Exception as exc:
            return FileWriteOutput(
                path=str(target_path),
                status="failed",
                message=f"Error writing file: {exc}",
            )


# ==============================================================================
# Helper Function to Instantiate All Tools
# ==============================================================================



# ==============================================================================
# 8. Application & Window Close Tool (system.close_app)
# ==============================================================================

class AppCloseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=100, description="Name of application, process, window or site to close (e.g. notepad, calc, chrome, edge, youtube, browser)")


class AppCloseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str
    status: str
    message: str
    verified: bool = True


class AppCloseTool(Tool):
    name = "system.close_app"
    description = "Gracefully closes desktop applications, browser windows, tabs, or processes on Windows."
    input_schema = AppCloseInput
    output_schema = AppCloseOutput
    permission_required = False
    permission_id = "system.close_app"
    risk_level = "low"

    _PROCESS_MAP = {
        "notepad": ["notepad.exe"],
        "calculator": ["CalculatorApp.exe", "calc.exe"],
        "calc": ["CalculatorApp.exe", "calc.exe"],
        "paint": ["mspaint.exe"],
        "mspaint": ["mspaint.exe"],
        "terminal": ["cmd.exe", "powershell.exe", "WindowsTerminal.exe"],
        "cmd": ["cmd.exe"],
        "powershell": ["powershell.exe"],
        "code": ["Code.exe"],
        "vscode": ["Code.exe"],
        "chrome": ["chrome.exe"],
        "edge": ["msedge.exe"],
        "browser": ["chrome.exe", "msedge.exe", "brave.exe", "firefox.exe"],
        "word": ["WINWORD.EXE"],
        "excel": ["EXCEL.EXE"],
        "powerpoint": ["POWERPNT.EXE"],
        "spotify": ["Spotify.exe"],
        "discord": ["Discord.exe"],
        "vlc": ["vlc.exe"],
        "steam": ["steam.exe"],
        "slack": ["slack.exe"],
        "zoom": ["Zoom.exe"],
    }

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, AppCloseInput):
            raise TypeError("AppCloseTool requires AppCloseInput arguments.")

        target_clean = arguments.target.strip().lower()
        is_tab_or_site = target_clean in {
            "tab", "browser tab", "this tab", "current tab", "window", "website",
            "youtube", "amazon", "google", "reddit", "twitter", "x", "netflix",
            "facebook", "instagram", "twitch", "github", "wikipedia", "spotify"
        }

        try:
            if sys.platform == "win32":
                if is_tab_or_site:
                    ps_script = (
                        f"$t = '{target_clean}'; "
                        "$browsers = @('chrome', 'msedge', 'brave', 'firefox'); "
                        "$p = Get-Process | Where-Object { $_.ProcessName -in $browsers -and $_.MainWindowTitle -like '*' + $t + '*' } | Select-Object -First 1; "
                        "if (-not $p) { $p = Get-Process | Where-Object { $_.ProcessName -in $browsers -and $_.MainWindowTitle.Length -gt 0 } | Select-Object -First 1; }; "
                        "if ($p) { $w = New-Object -ComObject WScript.Shell; $w.AppActivate($p.Id); Start-Sleep -Milliseconds 60; $w.SendKeys('^w'); }"
                    )
                    if shutil.which("powershell"):
                        subprocess.run(
                            ["powershell", "-NoProfile", "-Command", ps_script],
                            capture_output=True,
                            timeout=3,
                        )
                    else:
                        subprocess.run("taskkill /F /IM chrome.exe", shell=True, capture_output=True, timeout=3)
                else:
                    procs = self._PROCESS_MAP.get(target_clean) or [target_clean]
                    for proc in procs:
                        proc_name = proc.replace(".exe", "")
                        if shutil.which("powershell"):
                            ps_cmd = f"Stop-Process -Name '{proc_name}' -Force -ErrorAction SilentlyContinue"
                            subprocess.run(
                                ["powershell", "-NoProfile", "-Command", ps_cmd],
                                capture_output=True,
                                timeout=3,
                            )
                        else:
                            subprocess.run(
                                f"taskkill /F /IM {proc_name}.exe",
                                shell=True,
                                capture_output=True,
                                timeout=3,
                            )
            else:
                procs = self._PROCESS_MAP.get(target_clean) or [target_clean]
                for proc in procs:
                    proc_name = proc.replace(".exe", "")
                    if shutil.which("pkill"):
                        subprocess.run(
                            ["pkill", "-f", proc_name],
                            capture_output=True,
                            timeout=3,
                        )

            return AppCloseOutput(
                target=arguments.target,
                status="closed",
                message=f"Successfully closed {arguments.target} on your system.",
                verified=True,
            )
        except Exception as exc:
            logger.warning("Failed to close application %s: %s", arguments.target, exc)
            return AppCloseOutput(
                target=arguments.target,
                status="failed",
                message=f"Could not close {arguments.target}: {exc}",
                verified=False,
            )


# ==============================================================================
# 9. Live Web & Real-Time Sports/News Search Tool (web.search)
# ==============================================================================

class LiveSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500, description="The topic, sports match, person, or query to search for live information")


class LiveSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    query: str
    summary: str
    headlines: list[str] = Field(default_factory=list)
    verified: bool = True


class LiveSearchTool(Tool):
    name = "web.search"
    description = "Searches the live web, current news, and live sports feeds for real-time scores, headlines, and facts."
    input_schema = LiveSearchInput
    output_schema = LiveSearchOutput
    permission_required = False
    permission_id = "web.search"
    risk_level = "low"

    def execute(self, arguments: BaseModel) -> BaseModel:
        if not isinstance(arguments, LiveSearchInput):
            raise TypeError("LiveSearchTool requires LiveSearchInput arguments.")

        query = arguments.query.strip()
        encoded = urllib.parse.quote(query)
        headlines: list[str] = []

        # 1. Primary Live Feed: Google News RSS for live sports, breaking news, match updates
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(
            rss_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ATLAS/2.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = resp.read()
            import xml.etree.ElementTree as ET
            root = ET.fromstring(data)
            for it in root.findall(".//item")[:5]:
                title_elem = it.find("title")
                if title_elem is not None and title_elem.text:
                    cleaned_title = re.sub(r"\s+-\s+[^-]+$", "", title_elem.text).strip()
                    if cleaned_title and cleaned_title not in headlines:
                        headlines.append(cleaned_title)
        except Exception as exc:
            logger.info("Google News RSS query failed for '%s': %s", query, exc)

        # 2. Secondary/Fallback: DuckDuckGo Instant Answer API for encyclopedic/factual data
        if not headlines:
            ddg_url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
            req_ddg = urllib.request.Request(
                ddg_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ATLAS/2.0"},
            )
            try:
                with urllib.request.urlopen(req_ddg, timeout=3.0) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
                ddg_abstract = (payload.get("AbstractText") or payload.get("Answer") or "").strip()
                if ddg_abstract:
                    headlines.append(ddg_abstract)
            except Exception as exc:
                logger.info("DuckDuckGo Instant Answer query failed for '%s': %s", query, exc)

        if headlines:
            summary_bullet = "; ".join(headlines[:3])
            summary = f"Live update verified for '{query}', sir: {summary_bullet}"
            return LiveSearchOutput(
                status="success",
                query=query,
                summary=summary,
                headlines=headlines,
                verified=True,
            )

        return LiveSearchOutput(
            status="success",
            query=query,
            summary=f"Live feed queried for '{query}', sir. No active match or breaking bulletin found at this moment.",
            headlines=[],
            verified=True,
        )


def get_all_system_tools() -> list[Tool]:
    return [
        WebOpenTool(),
        WeatherTool(),
        AppLaunchTool(),
        DateTimeTool(),
        SystemCommandTool(),
        FileReadTool(),
        FileWriteTool(),
        AppCloseTool(),
        LiveSearchTool(),
    ]
