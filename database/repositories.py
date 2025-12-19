from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .models import Bot, Order, Trade
from typing import List, Optional
from sqlalchemy import update
import datetime


class BotRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_bot(self, user_id: str, pair: str, grid_config: dict) -> Bot:
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
        await self.session.commit()
        await self.session.refresh(bot)
        return bot

    async def get_bot(self, bot_id: int) -> Optional[Bot]:
        result = await self.session.execute(select(Bot).filter(Bot.id == bot_id))
        return result.scalars().first()

    async def update_status(self, bot_id: int, status: str):
        bot = await self.get_bot(bot_id)
        if bot:
            bot.status = status
            await self.session.commit()

    async def update_grid_config(self, bot_id: int, new_config: dict):
        bot = await self.get_bot(bot_id)
        if bot:
            # Update fields dynamically
            if "lower_limit" in new_config:
                bot.lower_limit = new_config["lower_limit"]
            if "upper_limit" in new_config:
                bot.upper_limit = new_config["upper_limit"]
            if "grid_count" in new_config:
                bot.grid_count = new_config["grid_count"]
            # Recalculate amount_per_grid if needed?
            # Assuming total investment is constant?
            # bot.amount_per_grid = bot.investment_amount / bot.grid_count
            # For now, trust the caller or keep amount_per_grid logic simple.

            await self.session.commit()
            await self.session.refresh(bot)
            return bot


class OrderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_order(self, bot_id: int, order_data: dict) -> Order:
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
        await self.session.commit()
        return order

    async def get_open_orders(self, bot_id: int) -> List[Order]:
        result = await self.session.execute(
            select(Order).filter(Order.bot_id == bot_id, Order.status == "OPEN")
        )
        return result.scalars().all()

    async def update_status(
        self, client_order_id: str, status: str, exchange_id: str = None
    ):
        result = await self.session.execute(
            select(Order).filter(Order.client_order_id == client_order_id)
        )
        order = result.scalars().first()

        if order:
            order.status = status
            if exchange_id:
                order.exchange_order_id = exchange_id
            await self.session.commit()
        return order


class TradeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_trade(self, bot_id: int, trade_data: dict) -> Trade:
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
        await self.session.commit()
        return trade
