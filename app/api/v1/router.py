"""V1 API Router consolidating sub-routers."""

from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.market import router as market_router
from app.api.v1.structure import router as structure_router
from app.api.v1.liquidity import router as liquidity_router
from app.api.v1.indicators import router as indicators_router
from app.api.v1.news import router as news_router
from app.api.v1.signals import router as signals_router
from app.api.v1.backtest import router as backtest_router
from app.api.v1.paper import router as paper_router
from app.api.v1.telegram import router as telegram_router

api_v1_router = APIRouter(prefix="/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(market_router)
api_v1_router.include_router(structure_router)
api_v1_router.include_router(liquidity_router)
api_v1_router.include_router(indicators_router)
api_v1_router.include_router(news_router)
api_v1_router.include_router(signals_router)
api_v1_router.include_router(backtest_router)
api_v1_router.include_router(paper_router)
api_v1_router.include_router(telegram_router)





