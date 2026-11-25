"""FastAPI Main Application Entrypoint."""

from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import logger
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
    
    # Fail fast if MOCK provider is configured for LIVE mode
    if settings.MODE.lower() == "live" and settings.MARKET_DATA_PROVIDER.lower() == "mock":
        raise RuntimeError("FATAL: Cannot run in LIVE mode with MOCK market data provider.")
        
    init_db()
    _ensure_required_columns()
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
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Forex Market Analysis, Market Structure, Liquidity Detection, and Signal Generation Engine",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
