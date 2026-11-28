"""Standalone connectivity test for the two MT5 demo accounts (MAIN and CENT).

Run from the repository root (Windows, MT5 terminal open)::

    python server/scripts/test_mt5_connection.py

This script only checks credentials and account balances. It never places an
order, regardless of ``LIVE_TRADING_ENABLED``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

# Optional: only needed if MT5 live execution is re-enabled later.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, ValueError):
    pass

from app.core.config import settings  # noqa: E402

try:  # Windows-only broker SDK; may be absent in CI or on non-Windows hosts.
    import MetaTrader5 as mt5  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on the local installation
    mt5 = None  # type: ignore[assignment]


REQUIRED_CREDENTIALS: Tuple[str, ...] = (
    "MT5_LOGIN_MAIN",
    "MT5_PASSWORD_MAIN",
    "MT5_SERVER_MAIN",
    "MT5_LOGIN_CENT",
    "MT5_PASSWORD_CENT",
    "MT5_SERVER_CENT",
)


def _credentials_present() -> bool:
    """Fail fast with a clear message when any .env value is missing."""
    missing = [
        name
        for name in REQUIRED_CREDENTIALS
        if not str(getattr(settings, name, "") or "").strip()
    ]
    if missing:
        print("❌ MT5 credentials missing in .env: " + ", ".join(missing))
        print("   Add them to server/.env (see server/.env.example) and retry.")
        return False
    return True


def _connect(label: str, login: str, password: str, server: str) -> bool:
    """Initialise MT5, log into one account, print its balance, then shut down."""
    if not mt5.initialize():
        error = getattr(mt5, "last_error", lambda: "unknown error")()
        print(f"❌ MT5 initialize() failed for {label}: {error}")
        print("   Ensure the MT5 terminal is open and running, then retry.")
        return False

    try:
        login_id = int(str(login).strip())
    except (TypeError, ValueError):
        print(f"❌ {label} login must be a numeric account number (got {login!r}).")
        mt5.shutdown()
        return False

    try:
        if not mt5.login(login_id, password, server):
            error = getattr(mt5, "last_error", lambda: "unknown error")()
            print(f"❌ {label} account login failed: {error}")
            print("   Check MT5_LOGIN_*, MT5_PASSWORD_* and MT5_SERVER_* in server/.env.")
            return False

        account_info = mt5.account_info()
        if account_info is None:
            error = getattr(mt5, "last_error", lambda: "unknown error")()
            print(f"❌ {label} connected but account_info() returned no data: {error}")
            return False

        balance: Optional[float] = getattr(account_info, "balance", None)
        print(f"✅ {label} Account Connected. Balance: {balance}")
        print("   Note: on a Cent account the balance is reported in cents — expected.")
        return True
    finally:
        # Shut the terminal connection down for this account before the next one.
        mt5.shutdown()


def main() -> int:
    if not _credentials_present():
        return 1

    if mt5 is None:
        print("❌ MetaTrader5 package is not installed or is unavailable on this host.")
        print("   Install it with: pip install MetaTrader5 (Windows + MT5 terminal required).")
        return 1

    main_ok = _connect(
        "MAIN",
        settings.MT5_LOGIN_MAIN,
        settings.MT5_PASSWORD_MAIN,
        settings.MT5_SERVER_MAIN,
    )
    cent_ok = _connect(
        "CENT",
        settings.MT5_LOGIN_CENT,
        settings.MT5_PASSWORD_CENT,
        settings.MT5_SERVER_CENT,
    )

    print(
        f" connection test only — no orders placed (LIVE_TRADING_ENABLED="
        f"{settings.LIVE_TRADING_ENABLED})."
    )
    return 0 if (main_ok and cent_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
