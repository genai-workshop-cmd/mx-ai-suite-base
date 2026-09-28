"""FastAPI routers for the control surface."""
from . import brain, runs, system

ROUTERS = [system.router, runs.router, brain.router]

__all__ = ["ROUTERS", "brain", "runs", "system"]
