from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from material_matcher.build_info import build_about_payload


def attach_frontend(app: FastAPI, dist_dir: Path) -> None:
    """Serve a built Vue SPA from the same process as the API.

    UI build/about metadata is attached here so deployment-facing metadata stays
    independent from the business API wrapper. The catch-all route is registered
    last: unknown /api paths remain 404 while application routes fall back to the
    SPA entry point. File resolution is constrained to dist_dir.
    """
    root = dist_dir.resolve()

    @app.get("/api/about", include_in_schema=False)
    def about() -> dict[str, str]:
        return build_about_payload()

    @app.get("/{frontend_path:path}", include_in_schema=False)
    def frontend(frontend_path: str):
        if frontend_path == "api" or frontend_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if not root.is_dir():
            raise HTTPException(status_code=404, detail="Frontend distribution is not installed")

        candidate = (root / frontend_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Not Found") from exc

        if frontend_path and candidate.is_file():
            return FileResponse(candidate)

        index = root / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Frontend distribution is not installed")
