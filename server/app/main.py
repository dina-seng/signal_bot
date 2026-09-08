"""FastAPI Main Application Entrypoint."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import logger
from app.core.database import init_db
from app.api.v1.router import api_v1_router


from app.services.telegram.scheduler import (
    start_scanner_scheduler,
    stop_scanner_scheduler,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info(f"Starting {settings.PROJECT_NAME} in [{settings.APP_ENV}] mode...")
    init_db()

    if settings.SCANNER_ENABLED:
        start_scanner_scheduler()
    else:
        logger.info("Automated market scanner disabled (SCANNER_ENABLED=False).")

    logger.info("Application startup complete.")
    yield
    logger.info("Application shutting down...")
    stop_scanner_scheduler()
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
