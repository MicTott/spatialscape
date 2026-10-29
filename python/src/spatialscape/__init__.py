"""spatialscape: build static spatialscape viewer bundles, or show an object from the session you are in."""

from importlib import import_module

__version__ = "0.5.0"

__all__ = ["Session", "show", "stop"]


def __getattr__(name: str):  # lazy: the CLI must not pay for importing the build stack at startup
    if name in ("show", "stop", "Session"):
        return getattr(import_module(".session", __name__), name)
    raise AttributeError(name)
