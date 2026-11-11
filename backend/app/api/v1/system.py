from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

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
