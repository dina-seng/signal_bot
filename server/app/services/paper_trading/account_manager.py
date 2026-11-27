"""Virtual Account and Margin Management Service."""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.logging import logger
from app.models.paper import VirtualAccount, PaperTrade, AccountTransaction
from app.schemas.paper_trading import VirtualAccountCreate, VirtualAccountResponse
from app.services.signals import RiskEngine


class VirtualAccountManager:
    """Manages virtual trading accounts, margin checks, balance, equity, and transactions."""

    # Columns that exist on every deployment, including databases that never
    # received the Milestone 2 user_id migration. Used only as a last-resort
    # fallback when the full ORM select fails with schema drift.
    _LEGACY_ACCOUNT_COLUMNS = (
        "id", "name", "initial_balance", "balance", "equity", "margin_used",
        "free_margin", "currency", "leverage", "is_active", "created_at", "updated_at",
    )

    def _legacy_active_account(
        self, db: Session, account_id: Optional[int] = None
    ) -> Optional[VirtualAccount]:
        """Select an account without referring to any post-migration column."""
        table = VirtualAccount.__table__
        columns = [table.c[name] for name in self._LEGACY_ACCOUNT_COLUMNS]
        stmt = select(*columns)
        stmt = (
            stmt.where(table.c.id == account_id)
            if account_id is not None
            else stmt.where(table.c.is_active == True)
        )
        row = db.execute(stmt.order_by(table.c.id.asc())).first()
        if row is None:
            return None
        return VirtualAccount(**dict(zip(self._LEGACY_ACCOUNT_COLUMNS, row)))

    def _find_active_account(self, db: Session) -> Optional[VirtualAccount]:
        """Look up the active account, surviving a missing user_id column."""
        try:
            return db.scalars(
                select(VirtualAccount)
                .where(VirtualAccount.is_active == True)
                .order_by(VirtualAccount.id.asc())
            ).first()
        except Exception as exc:
            # The failed statement poisons the transaction on Postgres. Roll back
            # first, otherwise every subsequent query fails with
            # InFailedSqlTransaction and the whole dashboard 500s.
            db.rollback()
            logger.warning(
                "Active-account query failed (schema drift, e.g. missing "
                "virtual_accounts.user_id): %s. Falling back to legacy columns.",
                exc,
            )
            try:
                return self._legacy_active_account(db)
            except Exception as legacy_exc:
                logger.error("Legacy active-account lookup also failed: %s", legacy_exc)
                return None

    @staticmethod
    def calculate_required_margin(symbol: str, lots: float, price: float, leverage: int = 100) -> float:
        """Calculate required margin in USD for a given position size."""
        lev = max(1, leverage)
        sym = symbol.upper().replace("%2F", "/").strip()
        if "XAU" in sym or "GOLD" in sym:
            # 1 standard lot of Gold = 100 oz
            contract_size = 100.0
            return round((lots * contract_size * price) / lev, 2)
        elif sym.startswith("USD/"):
            # Base currency is USD (e.g. USD/JPY, USD/CHF, USD/CAD) -> 1 lot = $100,000 USD
            return round((lots * 100000.0) / lev, 2)
        else:
            # Base currency is EUR, GBP, AUD, etc. -> Value in USD = lots * 100,000 * price
            return round((lots * 100000.0 * price) / lev, 2)

    def get_or_create_default_account(self, db: Session) -> VirtualAccount:
        """Fetch the active primary account or initialize one with $10,000."""
        account = self._find_active_account(db)
        if not account:
            try:
                account = VirtualAccount(
                    name="Primary Virtual Account",
                    initial_balance=10000.0,
                    balance=10000.0,
                    equity=10000.0,
                    margin_used=0.0,
                    free_margin=10000.0,
                    currency="USD",
                    leverage=100,
                    is_active=True,
                )
                db.add(account)
                db.commit()
                db.refresh(account)

                tx = AccountTransaction(
                    account_id=account.id,
                    transaction_type="DEPOSIT",
                    amount=10000.0,
                    balance_after=10000.0,
                    description="Initial Account Deposit",
                )
                db.add(tx)
                db.commit()
                logger.info(f"Initialized Primary Virtual Account #{account.id} with $10,000.")
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "Default-account creation failed (%s); retrying with legacy columns.", exc
                )
                try:
                    table = VirtualAccount.__table__
                    now = datetime.now(timezone.utc)
                    result = db.execute(
                        table.insert().values(
                            name="Primary Virtual Account",
                            initial_balance=10000.0,
                            balance=10000.0,
                            equity=10000.0,
                            margin_used=0.0,
                            free_margin=10000.0,
                            currency="USD",
                            leverage=100,
                            is_active=True,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    account_id = result.inserted_primary_key[0]
                    db.add(
                        AccountTransaction(
                            account_id=account_id,
                            transaction_type="DEPOSIT",
                            amount=10000.0,
                            balance_after=10000.0,
                            description="Initial Account Deposit",
                        )
                    )
                    db.commit()
                    account = self._legacy_active_account(db, account_id)
                    logger.info(f"Initialized Primary Virtual Account #{account_id} with $10,000.")
                except Exception as legacy_exc:
                    db.rollback()
                    logger.error("Legacy default-account creation failed: %s", legacy_exc)
                    account = self._find_active_account(db)
        return account

    def get_active_account(self, db: Session) -> Optional[VirtualAccount]:
        """Return the active paper account, or None. Never creates one implicitly."""
        return self._find_active_account(db)

    def create_account(self, db: Session, request: VirtualAccountCreate) -> VirtualAccount:
        """Create a new virtual account."""
        account = VirtualAccount(
            name=request.name,
            initial_balance=request.initial_balance,
            balance=request.initial_balance,
            equity=request.initial_balance,
            margin_used=0.0,
            free_margin=request.initial_balance,
            currency=request.currency.upper(),
            leverage=request.leverage,
            is_active=True,
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        tx = AccountTransaction(
            account_id=account.id,
            transaction_type="DEPOSIT",
            amount=request.initial_balance,
            balance_after=request.initial_balance,
            description="Initial Account Deposit",
        )
        db.add(tx)
        db.commit()
        return account

    def deposit_funds(self, db: Session, account_id: int, amount: float, description: str = "Deposit") -> VirtualAccount:
        """Deposit or withdraw funds from a virtual account."""
        account = db.get(VirtualAccount, account_id)
        if not account:
            raise ValueError(f"Virtual account #{account_id} not found.")

        account.balance = round(account.balance + amount, 2)
        account.equity = round(account.equity + amount, 2)
        account.free_margin = round(account.equity - account.margin_used, 2)
        account.updated_at = datetime.now(timezone.utc)

        tx_type = "DEPOSIT" if amount >= 0 else "WITHDRAWAL"
        tx = AccountTransaction(
            account_id=account.id,
            transaction_type=tx_type,
            amount=amount,
            balance_after=account.balance,
            description=description,
        )
        db.add(tx)
        db.commit()
        db.refresh(account)
        return account

    def reset_account(self, db: Session, account_id: int, initial_balance: float = 10000.0) -> VirtualAccount:
        """Reset virtual account: close all open positions and restore balance."""
        account = db.get(VirtualAccount, account_id)
        if not account:
            raise ValueError(f"Virtual account #{account_id} not found.")

        # Close all open/pending positions
        open_trades = db.scalars(
            select(PaperTrade).where(
                PaperTrade.account_id == account_id,
                PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED", "PENDING"]),
            )
        ).all()

        now = datetime.now(timezone.utc)
        for t in open_trades:
            t.status = "CLOSED"
            t.exit_reason = "ACCOUNT_RESET"
            t.closed_at = now

        account.initial_balance = initial_balance
        account.balance = initial_balance
        account.equity = initial_balance
        account.margin_used = 0.0
        account.free_margin = initial_balance
        account.updated_at = now

        tx = AccountTransaction(
            account_id=account.id,
            transaction_type="RESET",
            amount=initial_balance,
            balance_after=initial_balance,
            description="Account Reset to Initial Balance",
        )
        db.add(tx)
        db.commit()
        db.refresh(account)
        logger.info(f"Reset Virtual Account #{account_id} to ${initial_balance:,.2f}.")
        return account

    def recalculate_account_financials(self, db: Session, account: VirtualAccount) -> VirtualAccount:
        """Recalculate equity, margin used, and free margin from active positions."""
        active_trades = list(
            db.scalars(
                select(PaperTrade).where(
                    PaperTrade.account_id == account.id,
                    PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED"]),
                )
            ).all()
        )

        total_unrealized_pnl = sum(t.unrealized_pnl for t in active_trades)
        total_margin = sum(t.margin_used for t in active_trades)

        account.equity = round(account.balance + total_unrealized_pnl, 2)
        account.margin_used = round(total_margin, 2)
        account.free_margin = round(account.equity - account.margin_used, 2)
        account.updated_at = datetime.now(timezone.utc)
        db.commit()
        return account

    def get_account_response(self, db: Session, account: VirtualAccount) -> VirtualAccountResponse:
        """Construct full VirtualAccountResponse including live metrics."""
        self.recalculate_account_financials(db, account)

        open_trades = list(
            db.scalars(
                select(PaperTrade).where(
                    PaperTrade.account_id == account.id,
                    PaperTrade.status.in_(["OPEN", "PARTIALLY_CLOSED"]),
                )
            ).all()
        )
        closed_trades = list(
            db.scalars(
                select(PaperTrade).where(
                    PaperTrade.account_id == account.id,
                    PaperTrade.status == "CLOSED",
                )
            ).all()
        )

        floating_pnl = round(sum(t.unrealized_pnl for t in open_trades), 2)
        realized_pnl = round(sum(t.realized_pnl for t in closed_trades) + sum(t.realized_pnl for t in open_trades), 2)
        total_return_pct = round(((account.equity - account.initial_balance) / account.initial_balance) * 100.0, 2)
        margin_level = round((account.equity / account.margin_used) * 100.0, 2) if account.margin_used > 0 else 999.99

        return VirtualAccountResponse(
            id=account.id,
            name=account.name,
            initial_balance=account.initial_balance,
            balance=account.balance,
            equity=account.equity,
            margin_used=account.margin_used,
            free_margin=account.free_margin,
            margin_level_pct=margin_level,
            currency=account.currency,
            leverage=account.leverage,
            is_active=account.is_active,
            open_positions_count=len(open_trades),
            floating_pnl=floating_pnl,
            realized_pnl=realized_pnl,
            total_return_pct=total_return_pct,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )
