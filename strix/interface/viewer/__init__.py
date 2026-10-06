"""Local web viewer for Strix runs.

Serves a prebuilt single-page app that renders a run (live or finished) read
directly from the run's on-disk files. No cloud dependency, no file picker.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast


if TYPE_CHECKING:
    from collections.abc import Callable
    from http.server import ThreadingHTTPServer
    from pathlib import Path


def serve(
    run_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
    steer_handler: Callable[[str, str], bool] | None = None,
) -> tuple[ThreadingHTTPServer, str, str]:
    """Start the local viewer without importing its server during package setup."""
    serve_server = cast(
        "Callable[..., tuple[ThreadingHTTPServer, str, str]]",
        import_module("strix.interface.viewer.server").serve,
    )
    return serve_server(
        run_dir,
        host=host,
        port=port,
        open_browser=open_browser,
        steer_handler=steer_handler,
    )


__all__ = ["serve"]
