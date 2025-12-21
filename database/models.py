from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import datetime

Base = declarative_base()


class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True, nullable=False)  # Link to frontend user
    pair = Column(String, nullable=False)  # e.g. "BTC/USDT"

    # Credentials (WARNING: Plaintext for demo. Production strictly requires encryption)
    api_key = Column(String, nullable=True)
    secret_key = Column(String, nullable=True)

    status = Column(String, default="STOPPED")  # RUNNING, PAUSED, STOPPED
    mode = Column(String, default="MANUAL")  # AUTO, MANUAL

    # Grid Settings
    lower_limit = Column(Numeric(20, 8), nullable=False)
    upper_limit = Column(Numeric(20, 8), nullable=False)
    grid_count = Column(Integer, nullable=False)
    amount_per_grid = Column(Numeric(20, 8), nullable=False)
    quantity_type = Column(String, default="QUOTE")  # QUOTE, BASE
    grid_type = Column(String, default="ARITHMETIC")  # ARITHMETIC, GEOMETRIC

    # Auto Mode Settings
    risk_level = Column(Integer, nullable=True)  # Percentage, e.g. 10 for +/- 10%
    last_trailing_update = Column(DateTime, nullable=True)

    # Risk Management
    stop_loss = Column(Numeric(20, 8), nullable=True)
    take_profit = Column(Numeric(20, 8), nullable=True)
    current_balance = Column(Numeric(20, 8), default=0.0)

    orders = relationship("Order", back_populates="bot")
    trades = relationship("Trade", back_populates="bot")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False)

    # IDs
    exchange_order_id = Column(String, nullable=True)  # Assigned by exchange
    client_order_id = Column(
        String, unique=True, nullable=False
    )  # Assigned by us: bot_{id}_{nonce}

    # Order Details
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # BUY, SELL
    type = Column(String, default="LIMIT")
    price = Column(Numeric(20, 8), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)
    filled = Column(Numeric(20, 8), default=0.0)

    # Status
    status = Column(String, default="OPEN")  # OPEN, FILLED, CANCELED, VANISHED

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    bot = relationship("Bot", back_populates="orders")


class Trade(Base):
    """Immutable log of filled trades"""

    __tablename__ = "trade_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)

    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)

    fee = Column(Numeric(20, 8), default=0.0)
    fee_asset = Column(String, nullable=True)
    realized_pnl = Column(Numeric(20, 8), default=0.0)

    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    bot = relationship("Bot", back_populates="trades")
