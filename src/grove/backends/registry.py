"""Backend discovery via entry points."""

import logging
from importlib.metadata import entry_points

from grove.backends.base import Backend

logger = logging.getLogger(__name__)


def discover_backends() -> dict[str, type[Backend]]:
    """Discover installed backends via entry points."""
    backends: dict[str, type[Backend]] = {}
    eps = entry_points()
    if isinstance(eps, dict):
        group = eps.get("grove.backends", [])
    else:
        group = eps.select(group="grove.backends")
    for ep in group:
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, Backend):
                backends[ep.name] = cls
        except Exception as e:
            logger.warning("Failed to load backend plugin %r: %s", ep.name, e)
            continue
    return backends


def get_backend(name: str) -> Backend:
    """Get an instantiated backend by name."""
    backends = discover_backends()
    if name not in backends:
        available = ", ".join(backends.keys())
        raise ValueError(f"Unknown backend: {name}. Available: {available}")
    return backends[name]()


def detect_backends() -> list[Backend]:
    """Return list of backends detected on this system."""
    return [cls() for cls in discover_backends().values() if cls().detect()]
