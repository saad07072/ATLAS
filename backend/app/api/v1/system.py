from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.app.tools.browser_cdp import browser_cdp_manager
from backend.app.tools.macro_manager import macro_manager
from backend.app.tools.system_tools import get_system_vitals

router = APIRouter(prefix="/system", tags=["system"])


class SystemVitalsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu_percent: float
    memory_used_gb: float
    memory_total_gb: float
    memory_percent: float
    disk_free_gb: float
    disk_total_gb: float
    disk_percent: float
    battery_percent: int | None = None
    battery_plugged: str | None = None


@router.get("/vitals", response_model=SystemVitalsResponse)
def get_vitals_endpoint() -> SystemVitalsResponse:
    data = get_system_vitals()
    return SystemVitalsResponse(
        cpu_percent=data["cpu_percent"],
        memory_used_gb=data["memory_used_gb"],
        memory_total_gb=data["memory_total_gb"],
        memory_percent=data["memory_percent"],
        disk_free_gb=data["disk_free_gb"],
        disk_total_gb=data["disk_total_gb"],
        disk_percent=data["disk_percent"],
        battery_percent=data["battery_percent"],
        battery_plugged=data["battery_plugged"],
    )


class MacroListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    macros: list[dict[str, Any]]
    is_recording: bool
    active_macro: str | None = None
    buffer_count: int = 0


class MacroRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    macro_name: str | None = None


class MacroRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    message: str
    macro_name: str | None = None
    step_count: int = 0


class MacroPlayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    message: str
    macro_name: str
    executed_steps: list[dict[str, Any]]
    verified: bool


@router.get("/macros", response_model=MacroListResponse)
def list_macros_endpoint() -> MacroListResponse:
    return MacroListResponse(
        macros=macro_manager.list_macros(),
        is_recording=macro_manager.is_recording(),
        active_macro=macro_manager.active_recording_name(),
        buffer_count=macro_manager.buffer_count(),
    )


@router.post("/macros/record", response_model=MacroRecordResponse)
def record_macro_endpoint(payload: MacroRecordRequest) -> MacroRecordResponse:
    act = payload.action.strip().lower()
    if act == "start":
        name = payload.macro_name or "custom_routine"
        saved_key = macro_manager.start_recording(name)
        return MacroRecordResponse(
            status="recording",
            message=f"Macro recording initiated for '{saved_key}', sir.",
            macro_name=saved_key,
            step_count=0,
        )
    elif act in {"stop", "save"}:
        saved = macro_manager.stop_recording()
        if not saved:
            return MacroRecordResponse(
                status="failed",
                message="No active macro recording session was in progress, sir.",
                step_count=0,
            )
        return MacroRecordResponse(
            status="saved",
            message=f"Macro '{saved['name']}' saved successfully with {len(saved.get('steps', []))} steps, sir.",
            macro_name=saved["name"],
            step_count=len(saved.get("steps", [])),
        )
    elif act == "cancel":
        macro_manager.cancel_recording()
        return MacroRecordResponse(
            status="cancelled",
            message="Macro recording session cancelled, sir.",
            step_count=0,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Invalid recording action '{act}'")


@router.post("/macros/{name}/play", response_model=MacroPlayResponse)
def play_macro_endpoint(name: str) -> MacroPlayResponse:
    success, msg, steps = macro_manager.execute_macro(name)
    if not success and not steps:
        raise HTTPException(status_code=404, detail=msg)
    return MacroPlayResponse(
        status="success" if success else "failed",
        message=msg,
        macro_name=name,
        executed_steps=steps,
        verified=success,
    )


@router.delete("/macros/{name}")
def delete_macro_endpoint(name: str) -> dict[str, Any]:
    deleted = macro_manager.delete_macro(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Macro '{name}' not found.")
    return {"status": "success", "message": f"Macro '{name}' deleted.", "macro_name": name}


# ==============================================================================
# Browser CDP Management Endpoints
# ==============================================================================

class BrowserCDPStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connected: bool
    endpoint: str | None = None
    browser: str = "Unavailable"
    protocol_version: str | None = None
    user_agent: str | None = None
    error: str | None = None


class BrowserCDPTabModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    url: str
    type: str = "page"
    web_socket_debugger_url: str | None = None
    frontend_url: str | None = None


class BrowserCDPTabsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connected: bool
    tab_count: int
    tabs: list[BrowserCDPTabModel]


class BrowserCDPOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str


class BrowserCDPEvalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str


class BrowserCDPLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str | None = None
    port: int = 9222


@router.get("/browser/cdp/status", response_model=BrowserCDPStatusResponse)
def get_browser_cdp_status() -> BrowserCDPStatusResponse:
    info = browser_cdp_manager.get_version()
    return BrowserCDPStatusResponse(
        connected=info.get("connected", False),
        endpoint=info.get("endpoint"),
        browser=info.get("browser", "Unavailable"),
        protocol_version=info.get("protocol_version"),
        user_agent=info.get("user_agent"),
        error=info.get("error"),
    )


@router.get("/browser/cdp/tabs", response_model=BrowserCDPTabsResponse)
def get_browser_cdp_tabs() -> BrowserCDPTabsResponse:
    connected = browser_cdp_manager.is_connected()
    tabs = browser_cdp_manager.list_tabs()
    tab_models = [
        BrowserCDPTabModel(
            id=t.get("id", ""),
            title=t.get("title", ""),
            url=t.get("url", ""),
            type=t.get("type", "page"),
            web_socket_debugger_url=t.get("web_socket_debugger_url"),
            frontend_url=t.get("frontend_url"),
        )
        for t in tabs
    ]
    return BrowserCDPTabsResponse(
        connected=connected,
        tab_count=len(tab_models),
        tabs=tab_models,
    )


@router.post("/browser/cdp/tabs")
def open_browser_cdp_tab(payload: BrowserCDPOpenRequest) -> dict[str, Any]:
    return browser_cdp_manager.open_tab(payload.url)


@router.post("/browser/cdp/tabs/{tab_id}/activate")
def activate_browser_cdp_tab(tab_id: str) -> dict[str, Any]:
    ok = browser_cdp_manager.activate_tab(tab_id)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Could not activate tab '{tab_id}' via CDP.")
    return {"status": "success", "message": f"Activated tab {tab_id}", "tab_id": tab_id}


@router.delete("/browser/cdp/tabs/{tab_id}")
def close_browser_cdp_tab(tab_id: str) -> dict[str, Any]:
    ok = browser_cdp_manager.close_tab(tab_id)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Could not close tab '{tab_id}' via CDP.")
    return {"status": "success", "message": f"Closed tab {tab_id}", "tab_id": tab_id}


@router.post("/browser/cdp/tabs/{tab_id}/reload")
def reload_browser_cdp_tab(tab_id: str) -> dict[str, Any]:
    ok, msg = browser_cdp_manager.reload_tab(tab_id)
    return {"status": "success" if ok else "failed", "message": msg, "tab_id": tab_id}


@router.post("/browser/cdp/tabs/{tab_id}/eval")
def eval_browser_cdp_tab(tab_id: str, payload: BrowserCDPEvalRequest) -> dict[str, Any]:
    res = browser_cdp_manager.evaluate_expression(tab_id, payload.expression)
    return {"status": "success" if "error" not in res else "failed", "response": res}


@router.post("/browser/cdp/launch")
def launch_browser_cdp_endpoint(payload: BrowserCDPLaunchRequest) -> dict[str, Any]:
    ok, msg = browser_cdp_manager.launch_debug_browser(url=payload.url, port=payload.port)
    return {"status": "success" if ok else "failed", "message": msg, "port": payload.port}


