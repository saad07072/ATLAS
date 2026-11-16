from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

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

