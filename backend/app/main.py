"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import database
from app.config import DEMO_RULES_NOTICE, SYNTHETIC_NOTICE, get_settings
from app.deps import seed_demo_users
from app.routes import analytics, applications, auth, exceptions, rules
from app.services.verification_engine import seed_default_rules

log = logging.getLogger("loan_compliance")


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()
    with database.SessionLocal() as db:
        seed_default_rules(db)
        seed_demo_users(db)
        db.commit()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Loan Document Verification & Compliance Monitor",
        version="1.0.0",
        description=("Portfolio project. Pre-checks SYNTHETIC loan documents and routes exceptions to human reviewers. "
                     "It never approves or rejects a loan, and LLM output never decides compliance.\n\n"
                     f"**{SYNTHETIC_NOTICE}**\n\n**{DEMO_RULES_NOTICE}**"),
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH"], allow_headers=["Authorization", "Content-Type"])
    for r in (auth.router, applications.router, exceptions.router, rules.router, analytics.router):
        app.include_router(r)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):  # never leak internals or document text
        log.error("Unhandled error: %s", type(exc).__name__)
        return JSONResponse({"detail": "Internal server error."}, status_code=500)

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok", "llm_enabled": s.llm_enabled, "ocr_enabled": s.ocr_enabled}

    return app


app = create_app()
