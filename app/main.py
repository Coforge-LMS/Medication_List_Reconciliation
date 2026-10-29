"""FastAPI entry point. B1 stub: only /healthz; Sarthak grows it in B7."""

from fastapi import FastAPI

from app.version import __version__

app = FastAPI(title="MedRec", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
