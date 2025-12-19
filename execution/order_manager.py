import time
from typing import List
from database.repositories import OrderRepository, TradeRepository
from exchange.interface import ExchangeInterface
from config import ORDER_PREFIX
from utils.logger import setup_logger

logger = setup_logger("order_manager")


class OrderManager:
    def __init__(
        self,
        exchange: ExchangeInterface,
        order_repo: OrderRepository,
        trade_repo: TradeRepository,
    ):
        self.exchange = exchange
        self.order_repo = order_repo
        self.trade_repo = trade_repo

    def _generate_client_order_id(self, bot_id: int) -> str:
        return f"{ORDER_PREFIX}{bot_id}_{int(time.time() * 1000)}"

    async def place_orders(self, bot_id: int, orders_data: List[dict]):
        """
        Async placement of multiple orders.
        """
        # TODO: Use asyncio.gather for parallelism?
        # For safety/sequence, sequential is fine initially, or gather for speed.
        # Let's use sequential for safety first.

        for order_data in orders_data:
            client_id = self._generate_client_order_id(bot_id)
            db_order = dict(order_data)
            db_order["client_order_id"] = client_id

            try:
                # 2. Add to DB
                await self.order_repo.create_order(bot_id, db_order)

                # 3. Send to Exchange (ASYNC)
                response = await self.exchange.create_order(
                    symbol=order_data["symbol"],
                    side=order_data["side"],
                    type=order_data["type"],
                    quantity=order_data["quantity"],
                    price=order_data["price"],
                    client_order_id=client_id,
                )

                # 4. Update Exchange ID
                await self.order_repo.update_status(
                    client_id, "OPEN", exchange_id=str(response["id"])
                )
                logger.info(
                    f"Bot {bot_id}: Placed {order_data['side']} {order_data['symbol']} @ {order_data['price']}"
                )

            except Exception as e:
                logger.error(f"Bot {bot_id}: Failed to place order: {e}")
                await self.order_repo.update_status(client_id, "FAILED")

    async def cancel_bot_orders(self, bot_id: int):
        open_orders = await self.order_repo.get_open_orders(bot_id)

        for order in open_orders:
            try:
                success = await self.exchange.cancel_order(
                    order.symbol, order.exchange_order_id
                )
                if success:
                    await self.order_repo.update_status(
                        order.client_order_id, "CANCELED"
                    )
            except Exception as e:
                logger.error(
                    f"Bot {bot_id}: Failed to cancel order {order.exchange_order_id}: {e}"
                )

    async def sync_orders(self, bot_id: int) -> List[dict]:
        """
        Reconciliation Logic: 'Vanish Handling'
        Matches DB Orders vs Exchange Orders.
        Returns a list of orders that were confirmed FILLED in this sync.
        """
        filled_orders = []
        db_open_orders = await self.order_repo.get_open_orders(bot_id)
        if not db_open_orders:
            return filled_orders

        symbol = db_open_orders[0].symbol
        try:
            # Async fetch
            exchange_open_orders = await self.exchange.fetch_open_orders(symbol)
        except Exception as e:
            logger.error(f"Sync failed for bot {bot_id}: {e}")
            return filled_orders

        exchange_map = {o["client_order_id"]: o for o in exchange_open_orders}

        for db_order in db_open_orders:
            if db_order.client_order_id in exchange_map:
                continue

            # Vanished
            logger.warning(
                f"Bot {bot_id}: Order {db_order.client_order_id} vanished. Checking status..."
            )
            is_filled = await self._handle_vanished_order(bot_id, db_order)
            if is_filled:
                # Return the DB order object or a dict representation
                # We need details to place the counter order (price, qty)
                filled_orders.append(
                    {
                        "symbol": db_order.symbol,
                        "side": db_order.side,
                        "price": db_order.price,
                        "quantity": db_order.quantity,
                        "id": db_order.id,
                    }
                )
        return filled_orders

    async def _handle_vanished_order(self, bot_id: int, db_order) -> bool:
        """
        Queries specific order to find final state.
        Returns True if filled, False otherwise.
        """
        try:
            # Async fetch
            order_info = await self.exchange.fetch_order(
                db_order.symbol, db_order.exchange_order_id
            )

            if order_info["status"] == "closed":
                await self.order_repo.update_status(db_order.client_order_id, "FILLED")
                await self.trade_repo.log_trade(
                    bot_id,
                    {
                        "order_id": db_order.id,
                        "symbol": db_order.symbol,
                        "side": db_order.side,
                        "price": db_order.price,
                        "quantity": order_info["filled"],
                        "realized_pnl": 0.0,
                    },
                )
                logger.info(
                    f"Bot {bot_id}: Order {db_order.client_order_id} confirmed FILLED."
                )
                return True

            elif order_info["status"] == "canceled":
                await self.order_repo.update_status(
                    db_order.client_order_id, "CANCELED"
                )
                logger.info(
                    f"Bot {bot_id}: Order {db_order.client_order_id} was CANCELED."
                )
                return False

        except Exception as e:
            logger.error(
                f"Failed to resolve vanished order {db_order.client_order_id}: {e}"
            )
            return False

        return False
