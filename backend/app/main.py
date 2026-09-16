"""
Employee Platform Demo - FastAPI application entry point.

Stage 9: authentication, metadata-driven RBAC, the business-unit hierarchy,
metadata-driven applications/screens/dashboards, a generic workflow engine,
Employee Management, and the Leave Management System - the first business
process driven end to end by that engine.

Run locally from the "backend" directory:
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    access,
    auth,
    business_units,
    employees,
    health,
    leave,
    rbac,
    workflows,
)
from app.core.config import settings

app = FastAPI(
    title="Employee Platform Demo API",
    description="Metadata-driven enterprise platform - Leave Management System.",
    version="0.9.0",
)

# Browsers block a page on http://localhost:5173 from reading a response from
# http://127.0.0.1:8000 unless the server opts in. That opt-in is CORS.
app.add_middleware(
    CORSMiddleware,
    # Only the local Vite dev server, listed explicitly in Settings.
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoints live in routers under app/api/ and are attached here.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(access.router)
app.include_router(rbac.router)
app.include_router(business_units.router)
app.include_router(workflows.router)
app.include_router(employees.router)
app.include_router(leave.router)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    """Tiny landing response so hitting the base URL is not a 404."""
    return {"service": settings.app_name, "docs": "/docs"}
