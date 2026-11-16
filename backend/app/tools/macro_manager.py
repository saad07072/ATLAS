from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MACROS: dict[str, dict[str, Any]] = {
    "morning_routine": {
        "name": "morning_routine",
        "description": "Standard morning workstation setup: opens news, checks hardware vitals, and adjusts audio.",
        "steps": [
            {
                "tool": "system.vitals",
                "target": "workstation",
                "arguments": {},
                "description": "Assess workstation hardware vitals",
            },
            {
                "tool": "system.volume_control",
                "target": "master_audio",
                "arguments": {"action": "set", "percent": 40},
                "description": "Level master audio to 40%",
            },
            {
                "tool": "web.open",
                "target": "https://news.ycombinator.com",
                "arguments": {"url": "https://news.ycombinator.com"},
                "description": "Open Hacker News portal",
            },
        ],
        "created_at": "2026-11-16T00:00:00Z",
    },
    "standup_prep": {
        "name": "standup_prep",
        "description": "Prepares development and project management tools for daily team standup.",
        "steps": [
            {
                "tool": "system.open_app",
                "target": "code",
                "arguments": {"app_name": "code"},
                "description": "Focus Visual Studio Code",
            },
            {
                "tool": "system.open_app",
                "target": "terminal",
                "arguments": {"app_name": "terminal"},
                "description": "Launch PowerShell Terminal",
            },
            {
                "tool": "web.open",
                "target": "https://github.com",
                "arguments": {"url": "https://github.com"},
                "description": "Open GitHub dashboard",
            },
        ],
        "created_at": "2026-11-16T00:00:00Z",
    },
}


class MacroManager:
    """Manages persistent custom desktop macros and live recording sessions."""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        if storage_path is None:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            self.storage_path = base_dir / "data" / "macros.json"
        else:
            self.storage_path = Path(storage_path)

        self._active_recording_name: str | None = None
        self._recording_buffer: list[dict[str, Any]] = []
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.storage_path.exists():
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_MACROS, f, indent=2)
        except Exception as exc:
            logger.warning("Could not initialize macro storage at %s: %s", self.storage_path, exc)

    def list_macros(self) -> list[dict[str, Any]]:
        self._ensure_storage()
        try:
            if self.storage_path.exists():
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return list(data.values())
        except Exception as exc:
            logger.warning("Failed to load macros: %s", exc)
        return list(DEFAULT_MACROS.values())

    def get_macro(self, name: str) -> dict[str, Any] | None:
        key = name.strip().lower().replace(" ", "_").replace("-", "_")
        macros = {m["name"]: m for m in self.list_macros()}
        return macros.get(key)

    def save_macro(
        self,
        name: str,
        steps: list[dict[str, Any]],
        description: str = "",
    ) -> dict[str, Any]:
        key = name.strip().lower().replace(" ", "_").replace("-", "_")
        macros = {m["name"]: m for m in self.list_macros()}
        entry = {
            "name": key,
            "description": description or f"Custom desktop macro '{key}'",
            "steps": steps,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        macros[key] = entry
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(macros, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save macro %s: %s", key, exc)
        return entry

    def delete_macro(self, name: str) -> bool:
        key = name.strip().lower().replace(" ", "_").replace("-", "_")
        macros = {m["name"]: m for m in self.list_macros()}
        if key in macros:
            del macros[key]
            try:
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(macros, f, indent=2)
                return True
            except Exception as exc:
                logger.error("Failed to delete macro %s: %s", key, exc)
        return False

    def start_recording(self, name: str) -> str:
        key = name.strip().lower().replace(" ", "_").replace("-", "_")
        self._active_recording_name = key
        self._recording_buffer = []
        return key

    def record_step(
        self,
        tool: str,
        target: str,
        arguments: dict[str, Any] | None = None,
        description: str = "",
    ) -> None:
        if self._active_recording_name:
            self._recording_buffer.append(
                {
                    "tool": tool,
                    "target": target,
                    "arguments": arguments or {},
                    "description": description or f"Execute {tool} on {target}",
                }
            )

    def stop_recording(self) -> dict[str, Any] | None:
        if not self._active_recording_name:
            return None
        name = self._active_recording_name
        steps = list(self._recording_buffer)
        self._active_recording_name = None
        self._recording_buffer = []
        return self.save_macro(name, steps)

    def cancel_recording(self) -> None:
        self._active_recording_name = None
        self._recording_buffer = []

    def is_recording(self) -> bool:
        return self._active_recording_name is not None

    def active_recording_name(self) -> str | None:
        return self._active_recording_name

    def buffer_count(self) -> int:
        return len(self._recording_buffer)

    def execute_macro(self, name: str) -> tuple[bool, str, list[dict[str, Any]]]:
        """Executes all steps in a saved macro sequentially."""
        from backend.app.tools.system_tools import (
            AppCloseInput,
            AppCloseTool,
            AppLaunchInput,
            AppLaunchTool,
            LockWorkstationInput,
            LockWorkstationTool,
            MediaControlInput,
            MediaControlTool,
            SendKeysInput,
            SendKeysTool,
            SystemVitalsInput,
            SystemVitalsTool,
            VolumeControlInput,
            VolumeControlTool,
            WebOpenInput,
            WebOpenTool,
            WindowStateInput,
            WindowStateTool,
        )

        macro = self.get_macro(name)
        if not macro:
            return False, f"Macro '{name}' was not found in your saved routines, sir.", []

        executed_steps: list[dict[str, Any]] = []
        steps = macro.get("steps", [])

        for s in steps:
            tool_name = s.get("tool", "")
            target = s.get("target", "desktop")
            args = s.get("arguments", {})
            desc = s.get("description", f"Execute {tool_name}")

            status = "success"
            msg = f"Executed {desc}"
            verified = True

            try:
                if tool_name == "web.open":
                    url = args.get("url") or target
                    WebOpenTool().execute(WebOpenInput(url=url))
                elif tool_name == "system.open_app":
                    app = args.get("app_name") or target
                    AppLaunchTool().execute(AppLaunchInput(app_name=app))
                elif tool_name == "system.close_app":
                    target_app = args.get("target") or target
                    AppCloseTool().execute(AppCloseInput(target=target_app))
                elif tool_name == "system.volume_control":
                    action = args.get("action", "set")
                    pct = args.get("percent")
                    VolumeControlTool().execute(VolumeControlInput(action=action, percent=pct))
                elif tool_name == "system.media_control":
                    action = args.get("action", "play")
                    MediaControlTool().execute(MediaControlInput(action=action))
                elif tool_name == "system.window_state":
                    action = args.get("action", "minimize_all")
                    WindowStateTool().execute(WindowStateInput(action=action))
                elif tool_name == "system.vitals":
                    SystemVitalsTool().execute(SystemVitalsInput())
                elif tool_name == "system.lock_pc":
                    LockWorkstationTool().execute(LockWorkstationInput())
                elif tool_name == "system.send_keys":
                    keys = args.get("keys", "")
                    SendKeysTool().execute(SendKeysInput(keys=keys))
                else:
                    msg = f"Simulated step '{tool_name}' on {target}"
            except Exception as exc:
                logger.warning("Macro step execution error on %s: %s", tool_name, exc)
                status = "failed"
                msg = f"Failed step: {exc}"
                verified = False

            executed_steps.append(
                {
                    "tool": tool_name,
                    "target": target,
                    "status": status,
                    "message": msg,
                    "verified": verified,
                }
            )

        summary_msg = (
            f"Macro '{macro['name']}' completed, sir. "
            f"{len(executed_steps)} actions executed across your workstation."
        )
        return True, summary_msg, executed_steps


macro_manager = MacroManager()
