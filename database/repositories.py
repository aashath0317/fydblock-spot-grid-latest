from sqlalchemy.orm import Session
from .models import Bot, Order, Trade
from typing import List, Optional
import datetime


class BotRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_bot(self, user_id: str, pair: str, grid_config: dict) -> Bot:
        bot = Bot(
            user_id=user_id,
            pair=pair,
            upper_limit=grid_config["upper_limit"],
            lower_limit=grid_config["lower_limit"],
            grid_count=grid_config["grid_count"],
            amount_per_grid=grid_config["amount_per_grid"],
            risk_level=grid_config.get("risk_level"),
            stop_loss=grid_config.get("stop_loss"),
            take_profit=grid_config.get("take_profit"),
            status="STOPPED",
            mode=grid_config.get("mode", "MANUAL"),
        )
        self.session.add(bot)
        self.session.commit()
        self.session.refresh(bot)
        return bot

    def get_bot(self, bot_id: int) -> Optional[Bot]:
        return self.session.query(Bot).filter(Bot.id == bot_id).first()

    def update_status(self, bot_id: int, status: str):
        bot = self.get_bot(bot_id)
        if bot:
            bot.status = status
            self.session.commit()


class OrderRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_order(self, bot_id: int, order_data: dict) -> Order:
        order = Order(
            bot_id=bot_id,
            client_order_id=order_data["client_order_id"],
            symbol=order_data["symbol"],
            side=order_data["side"],
            price=order_data["price"],
            quantity=order_data["quantity"],
            status="OPEN",
        )
        self.session.add(order)
        self.session.commit()
        return order

    def get_open_orders(self, bot_id: int) -> List[Order]:
        return (
            self.session.query(Order)
            .filter(Order.bot_id == bot_id, Order.status == "OPEN")
            .all()
        )

    def update_status(self, client_order_id: str, status: str, exchange_id: str = None):
        order = (
            self.session.query(Order)
            .filter(Order.client_order_id == client_order_id)
            .first()
        )
        if order:
            order.status = status
            if exchange_id:
                order.exchange_order_id = exchange_id
            self.session.commit()
        return order


class TradeRepository:
    def __init__(self, session: Session):
        self.session = session

    def log_trade(self, bot_id: int, trade_data: dict) -> Trade:
        trade = Trade(
            bot_id=bot_id,
            order_id=trade_data.get("order_id"),
            symbol=trade_data["symbol"],
            side=trade_data["side"],
            price=trade_data["price"],
            quantity=trade_data["quantity"],
            fee=trade_data.get("fee", 0.0),
            fee_asset=trade_data.get("fee_asset"),
            realized_pnl=trade_data.get("realized_pnl", 0.0),
        )
        self.session.add(trade)
        self.session.commit()
        return trade
