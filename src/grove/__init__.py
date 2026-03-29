"""grove — persistent memory and identity for AI coding assistants."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("grove")
except PackageNotFoundError:
    __version__ = "dev"
