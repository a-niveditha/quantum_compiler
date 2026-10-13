"""
HTTP API for the dashboard (frontend/). Compiles one benchmark live with every
method and returns the metrics next to the published CSV values.

RUN (from backend/, venv active; startup takes ~10-20 s while models load):
    python -m uvicorn api.server:app --port 8000

Endpoints:
    GET  /api/health    -> {"ready": bool}
    GET  /api/options   -> device (qubits, couplers, error rates), circuits, methods
    POST /api/compile   {"circuit": "dj"} -> per-method metrics, layouts, drawings
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.service import CompileService

state: dict = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    state["service"] = CompileService()
    print(f"API ready (models loaded in {state['service'].startup_seconds:.1f} s)", flush=True)
    yield
    state.clear()


app = FastAPI(title="Quantum compiler demo API", lifespan=lifespan)
# The Vite dev server proxies /api, but allow direct calls from it as well.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["*"])


class CompileRequest(BaseModel):
    circuit: str


@app.get("/api/health")
def health():
    return {"ready": "service" in state}


@app.get("/api/options")
def options():
    return state["service"].options()


@app.post("/api/compile")
def compile_circuit(req: CompileRequest):
    try:
        return state["service"].compile(req.circuit)
    except KeyError:
        raise HTTPException(404, f"Unknown circuit {req.circuit!r}")
