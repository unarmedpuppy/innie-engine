"""Backend discovery via entry points."""

from importlib.metadata import entry_points

from innie.backends.base import Backend


def discover_backends() -> dict[str, type[Backend]]:
    """Discover installed backends via entry points."""
    backends: dict[str, type[Backend]] = {}
    eps = entry_points()
    if isinstance(eps, dict):
        group = eps.get("innie.backends", [])
    else:
        group = eps.select(group="innie.backends")
    for ep in group:
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, Backend):
                backends[ep.name] = cls
        except Exception:
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
