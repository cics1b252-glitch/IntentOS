"""Intent OS — FastAPI Server.

REST API layer for the Intent OS Kernel.
The Kernel remains independent — this is just an interface.

Usage:
    # Development
    uvicorn intent_kernel.server.app:app --reload

    # Production
    intent-os-server
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from intent_kernel.application import ApplicationFactory, KernelBuilder
from intent_kernel.kernel import Kernel
from product_bridge import ProductBridge


# ---------------------------------------------------------------------------
# Lifespan — Kernel initialization
# ---------------------------------------------------------------------------

_kernel: Kernel | None = None
_factory: ApplicationFactory | None = None
_product_bridge: ProductBridge | None = None


def configure_factory(factory: ApplicationFactory) -> None:
    """Inject the shared Composition Root before server startup."""
    global _factory, _kernel, _product_bridge
    _factory = factory
    _kernel = None
    _product_bridge = None


def get_kernel() -> Kernel:
    """Get the singleton Kernel instance."""
    global _kernel, _factory
    if _kernel is None:
        pkb_path = os.environ.get("INTENT_OS_PKB_PATH", "~/.intent-os/pkb")
        _factory = _factory or ApplicationFactory(
            KernelBuilder()
            .with_pkb_path(pkb_path)
            .with_environment(dict(os.environ))
        )
        _kernel = _factory.get_kernel()

    return _kernel


def get_product_bridge() -> ProductBridge:
    """Return the product adapter over the same canonical composition root."""
    global _factory, _product_bridge
    if _factory is None:
        get_kernel()
    if _product_bridge is None:
        data_root = os.environ.get("INTENTOS_DATA_ROOT", "~/.intent-os")
        _product_bridge = ProductBridge(
            factory=_factory,
            data_root=os.path.expanduser(data_root),
        )
    return _product_bridge


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan — initialize Kernel on startup."""
    kernel = get_kernel()
    print(f"🧠 Intent OS Kernel v{kernel.version} started")
    print(f"   Constitution: v{kernel.constitution.version}")
    print(f"   Providers: {kernel.providers.available}")
    print(f"   Modules: {kernel.router.registered_modules}")
    yield
    print("🧠 Intent OS Kernel shut down")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Intent OS API",
    description="Cognitive Operating System — REST API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class ProcessRequest(BaseModel):
    """Request to process an intent."""
    text: str = Field(..., description="User intent text")
    context: dict[str, Any] = Field(default_factory=dict, description="Additional context")
    mode: str = Field(default="auto", description="Processing mode: auto|quick|basic|detail|expert|architect")


class ProductPresentationResponse(BaseModel):
    visible_state: str
    title: str
    tone: str
    response_origin: str
    show_provider_execution: bool
    show_mission: bool
    show_missing_capabilities: bool
    requires_authorization: bool
    requires_confirmation: bool
    suggested_actions: list[str] = []
    interactive_actions: list[str] = []


class ProcessResponse(BaseModel):
    """Typed product response preserving the canonical cognitive envelope."""

    model_config = ConfigDict(extra="allow")

    product_contract_version: str
    text: str
    status: str
    execution_mode: str
    response_origin: str
    confidence: float
    epistemic_status: str
    provider: str | None = None
    provider_called: bool = False
    resource_provenance: list[str] = []
    mission_id: str | None = None
    verification_evidence: list[dict[str, Any]] = []
    limitations: list[str] = []
    missing_capabilities: list[str] = []
    authorization_requirements: list[str] = []
    next_actions: list[str] = []
    ok: bool
    presentation: ProductPresentationResponse
    response_authority: str
    product_presentation_authority: str


class QueryResponse(BaseModel):
    """Response from PKB query."""
    events: list[dict[str, Any]]
    total: int


class StatusResponse(BaseModel):
    """Kernel status."""
    version: str
    constitution_version: str
    providers: list[str]
    modules: list[str]
    pkb_path: str


class EventResponse(BaseModel):
    """Single PKB event."""
    id: str
    type: str
    domain: str
    title: str
    summary: str
    confidence: float
    lifecycle: str
    version: int
    created_at: str


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("INTENT_OS_API_KEY")


async def verify_api_key(authorization: str | None = Header(None)):
    """Verify API key if configured."""
    if API_KEY is None:
        return True  # No auth configured — open access

    if authorization is None:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.replace("Bearer ", "")
    if token != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

    return True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/v1/status", response_model=StatusResponse)
async def status():
    """Get Kernel status."""
    kernel = get_kernel()
    s = kernel.status()
    return StatusResponse(**s)


@app.post("/api/v1/process", response_model=ProcessResponse)
async def process_intent(req: ProcessRequest, _: bool = Depends(verify_api_key)):
    """Process through ProductBridge without overriding canonical semantics."""
    # Transport context is subordinate: it cannot replace the route-selected
    # action or the typed user text accepted by this endpoint.
    request = {**dict(req.context), "action": "intent", "message": req.text}
    # The historical `mode` input remains accepted as a presentation preference,
    # but it cannot override CognitiveResponse.execution_mode.
    request["requested_presentation_mode"] = req.mode
    result = await get_product_bridge().dispatch(request)
    return ProcessResponse(**result)


@app.get("/api/v1/query", response_model=QueryResponse)
async def query_pkb(q: str = "", _: bool = Depends(verify_api_key)):
    """Query the PKB."""
    kernel = get_kernel()
    events = await kernel.query(q)
    return QueryResponse(
        events=[
            {
                "id": e.id,
                "type": e.type.value,
                "domain": e.domain.value,
                "title": e.title,
                "summary": e.summary,
                "confidence": e.confidence,
                "lifecycle": e.lifecycle.value,
                "version": e.version,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        total=len(events),
    )


@app.get("/api/v1/pkb/events", response_model=list[EventResponse])
async def list_events(
    limit: int = 50,
    domain: str | None = None,
    _: bool = Depends(verify_api_key),
):
    """List PKB events."""
    from intent_kernel.types import Domain, EventLifecycle, EventType, QueryFilters

    kernel = get_kernel()
    filters = QueryFilters(limit=limit)
    if domain:
        try:
            filters.domain = Domain(domain)
        except ValueError:
            pass

    events = await kernel.query("")
    return [
        EventResponse(
            id=e.id,
            type=e.type.value,
            domain=e.domain.value,
            title=e.title,
            summary=e.summary,
            confidence=e.confidence,
            lifecycle=e.lifecycle.value,
            version=e.version,
            created_at=e.created_at.isoformat(),
        )
        for e in events[:limit]
    ]


@app.delete("/api/v1/pkb/events/{event_id}")
async def delete_event(event_id: str, _: bool = Depends(verify_api_key)):
    """Delete a PKB event (Soberania)."""
    kernel = get_kernel()
    deleted = await kernel.knowledge.store.delete(event_id)
    if not deleted:
        raise HTTPException(404, "Event not found")
    return {"deleted": True, "id": event_id}


@app.delete("/api/v1/pkb")
async def clear_pkb(_: bool = Depends(verify_api_key)):
    """Clear all PKB data (Soberania)."""
    kernel = get_kernel()
    await kernel.knowledge.delete_all()
    return {"cleared": True}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run():
    """Entry point for the server."""
    import uvicorn
    port = int(os.environ.get("INTENT_OS_PORT", "8000"))
    host = os.environ.get("INTENT_OS_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
