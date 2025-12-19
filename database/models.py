from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
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
    status = Column(String, default="STOPPED")  # RUNNING, PAUSED, STOPPED
    mode = Column(String, default="MANUAL")  # AUTO, MANUAL

    # Grid Settings
    lower_limit = Column(Float, nullable=False)
    upper_limit = Column(Float, nullable=False)
    grid_count = Column(Integer, nullable=False)
    amount_per_grid = Column(Float, nullable=False)

    # Auto Mode Settings
    risk_level = Column(Integer, nullable=True)  # Percentage, e.g. 10 for +/- 10%
    last_trailing_update = Column(DateTime, nullable=True)

    # Risk Management
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)

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
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)

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
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)

    fee = Column(Float, default=0.0)
    fee_asset = Column(String, nullable=True)
    realized_pnl = Column(Float, default=0.0)

    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    bot = relationship("Bot", back_populates="trades")
