"""Legacy Vercel entrypoint — prefer server.app:app via pyproject.toml."""

from server.app import app  # noqa: F401
