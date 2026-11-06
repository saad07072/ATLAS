"""
Root shim for ATLAS backend app.
Allows running 'uvicorn app.main:app' directly from the repository root.
"""
from backend.app.main import app

__all__ = ["app"]
