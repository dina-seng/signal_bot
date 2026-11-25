"""FastAPI Main Application Entrypoint."""

from contextlib import asynccontextmanager
import os
import time
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.proxy_headers import ProxyHeadersMiddleware
from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import metrics
from app.core.security import decode_session_token
from app.core.database import engine, init_db
from sqlalchemy import inspect, text
from app.api.v1.router import api_v1_router 
from datetime import datetime, timezone 


from app.services.telegram.scheduler import (
    start_scanner_scheduler,
    stop_scanner_scheduler,
)


def _ensure_required_columns() -> None:
    """Idempotent schema guard for columns added after the initial deployment.

    Alembic remains the source of truth; this only heals a database that has not
    yet received migration c7a4f2b19d30 (e.g. a deploy where build-time
    migrations targeted a different DATABASE_URL).
    """
    required = {"paper_trades": ("broker_profile",)}
    for table, columns in required.items():
        if table not in inspect(engine).get_table_names():
            continue
        existing = {c["name"] for c in inspect(engine).get_columns(table)}
        for column in columns:
            if column not in existing:
                logger.warning(f"[schema] Adding missing column {table}.{column}")
                with engine.begin() as conn:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(64)")
                    )


def _log_alembic_state() -> None:
    """Log alembic current/heads equivalents so Render proves the DB revision."""
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        ini_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic.ini"
        )
        cfg = Config(ini_path)
        heads = ScriptDirectory.from_config(cfg).get_heads()
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        logger.info(f"[alembic] current: {current or '(none)'}")
        logger.info(f"[alembic] heads: {', '.join(heads) or '(none)'}")
    except Exception as exc:
        logger.warning(f"[alembic] Could not inspect migration state: {exc}")


def _heal_pending_market_trades() -> None:
    """Repair legacy auto-executed MARKET rows left in PENDING.

    Older deployments could persist a signal fill as PENDING, which made the
    position invisible to /paper/positions?status=OPEN and to the atomic
    /paper/summary snapshot ("ghost trade"). Genuine LIMIT/STOP orders and
    historical CLOSED/CANCELLED rows are never touched.
    """
    try:
        # Imported lazily so the test suite's patched SessionLocal is honoured.
        from app.core.database import SessionLocal
        from app.models.paper import PaperTrade, VirtualAccount
        from app.services.paper_trading.account_manager import VirtualAccountManager

        db = SessionLocal()
        try:
            manager = VirtualAccountManager()
            pending = db.query(PaperTrade).filter(PaperTrade.status == "PENDING").all()
            ghosts = [
                t for t in pending
                if str(t.order_type or "").upper().strip() == "MARKET"
            ]
            if not ghosts:
                return

            touched_accounts = set()
            for trade in ghosts:
                account = db.get(VirtualAccount, trade.account_id)
                trade.status = "OPEN"
                trade.target_entry_price = None
                if account is not None and not trade.margin_used:
                    trade.margin_used = manager.calculate_required_margin(
                        symbol=trade.symbol,
                        lots=trade.remaining_position_size,
                        price=trade.entry_price,
                        leverage=account.leverage,
                    )
                touched_accounts.add(trade.account_id)
                logger.warning(
                    f"[startup] Healed ghost trade #{trade.id} ({trade.symbol}): "
                    "PENDING MARKET order -> OPEN."
                )
            db.commit()
            for account_id in touched_accounts:
                account = db.get(VirtualAccount, account_id)
                if account is not None:
                    manager.recalculate_account_financials(db, account)
        finally:
            db.close()
    except Exception as exc:
        # Startup should never fail because of a data-repair best effort.
        logger.warning(f"[startup] Could not heal PENDING market trades: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info(f"Starting {settings.PROJECT_NAME} in [{settings.APP_ENV}] mode (MODE={settings.MODE})...")
    logger.info(f"Risk per order: MAX_RISK_PERCENT = {settings.MAX_RISK_PERCENT:.1f}% (source: settings/.env)")
    if (
        settings.APP_ENV.lower() in {"production", "prod"}
        and settings.JWT_SECRET_KEY == "dev-only-session-secret-change-me"
    ):
        logger.warning("JWT_SECRET_KEY is the development default — set a strong secret in env.")
    
    # Fail fast if MOCK provider is configured for LIVE mode
    if settings.MODE.lower() == "live" and settings.MARKET_DATA_PROVIDER.lower() == "mock":
        raise RuntimeError("FATAL: Cannot run in LIVE mode with MOCK market data provider.")
        
    init_db()
    _ensure_required_columns()
    _log_alembic_state()
    _heal_pending_market_trades()

    # Persistent shared HTTP client — eliminates per-request TCP/TLS handshake overhead.
    # Providers receive this via dependency injection for high-frequency paths.
    app.state.http_client = httpx.AsyncClient(
        timeout=15.0,
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
    )

    if settings.SCANNER_ENABLED:
        start_scanner_scheduler()
    else:
        logger.info("Automated market scanner disabled (SCANNER_ENABLED=False).")

    logger.info("Application startup complete.")
    yield
    logger.info("Application shutting down...")
    stop_scanner_scheduler()
    await app.state.http_client.aclose()
    logger.info("Application shutdown complete.")


app = FastAPI(
    title=settings.API_TITLE,
    version="1.0.0",
    description=settings.API_DESCRIPTION,
    lifespan=lifespan,
)

# ── Reverse-proxy trust (MUST be outermost — added last in Starlette) ─────────
# Netlify proxies /api/* to this Render backend and sets X-Forwarded-Proto,
# X-Forwarded-For, and X-Forwarded-Host.  Without this middleware FastAPI sees
# scheme=http and host=signal-bot-hemp.onrender.com, which causes:
#   • secure=True cookies to be silently dropped (http context)
#   • redirects that point at the Render domain instead of the frontend
# trusted_hosts="*" is safe here: Render's inbound network already constrains
# who can reach the backend; the middleware only strips/reorders headers.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# CORS Middleware — exact frontend origin(s) only, no wildcard with credentials.
# settings.FRONTEND_ORIGIN is normalised to a non-empty List[str] by config.py,
# so a blank/malformed env var can never silently allow zero origins.
_frontend_origins = list(settings.FRONTEND_ORIGIN)
logger.info(f"🌐 CORS configured for origins: {settings.FRONTEND_ORIGIN}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Accept",
        "Origin",
        "X-Requested-With",
        "X-Request-ID",
    ],
    expose_headers=["X-Response-Time-Ms"],
    max_age=settings.CORS_MAX_AGE_SECONDS,
)


@app.middleware("http")
async def record_request_latency(request: Request, call_next):
    """Measure every request and log the total at DEBUG level."""
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
    metrics.record_request(request.url.path, duration_ms)
    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    logger.debug(
        "[latency] %s %s completed in %.2fms",
        request.method,
        request.url.path,
        duration_ms,
    )
    return response


# Session guard is innermost: CORS still answers OPTIONS and decorates 401s,
# while latency logging still measures the full request including auth.
_PUBLIC_PATHS = {"/ping", "/", "/docs", "/redoc", "/openapi.json"}
_PUBLIC_PREFIXES = ("/api/v1/auth/", "/api/v1/health")
_TELEGRAM_WEBHOOK = "/api/v1/telegram/webhook"


@app.middleware("http")
async def enforce_session_auth(request: Request, call_next):
    """Require a signed session cookie for every non-public API request."""
    path = request.url.path
    is_public = (
        not settings.AUTH_ENABLED
        or request.method == "OPTIONS"
        or path in _PUBLIC_PATHS
        or path.startswith(_PUBLIC_PREFIXES)
        or path == _TELEGRAM_WEBHOOK
    )
    if is_public:
        return await call_next(request)

    claims = decode_session_token(request.cookies.get(settings.SESSION_COOKIE_NAME))
    if claims is None:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    request.state.user = claims
    return await call_next(request)


# Include API Routers
app.include_router(api_v1_router, prefix="/api")    

@app.api_route("/ping", methods=["GET", "HEAD"], tags=["health"])
def ping():
    """Ultra-lightweight keepalive endpoint for Render free tier."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}



@app.get("/")
def root():
    """Root landing endpoint."""
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "version": "1.0.0",
        "docs_url": "/docs",
        "health_url": "/api/v1/health",
    }


@app.get("/dashboard", include_in_schema=False)
def dashboard_entry():
    """Authenticated SPA entry route.

    Netlify serves the built React app from this path on the frontend origin.
    Keeping a light backend counterpart lets the same-origin session guard be
    verified end-to-end (cookie -> 200, no bounce to /login).
    """
    return {"spa": "/dashboard", "authenticated": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
