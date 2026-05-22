"""Mijia API Server application package."""

from server.app import create_app
from server.config import ServerSettings

__all__ = ["ServerSettings", "create_app"]
