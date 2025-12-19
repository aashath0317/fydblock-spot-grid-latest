from typing import List, Dict
from execution.order_manager import OrderManager
from strategies.grid_math import calculate_grid_levels
from database.models import Bot
from utils.logger import setup_logger

logger = setup_logger("grid_strategy")


class GridStrategy:
    def __init__(self, order_manager: OrderManager):
        self.order_manager = order_manager

    async def place_initial_grid(self, bot: Bot, current_price: float):
        """
        Calculates grid levels, rebalances portfolio, and places OPEN orders.
        """
        logger.info(f"Bot {bot.id}: Calculating initial grid...")

        # 1. Calc Levels
        levels = calculate_grid_levels(bot.lower_limit, bot.upper_limit, bot.grid_count)

        orders_to_place = []
        needed_base_asset = 0.0

        # 2. Plan Orders
        for price in levels:
            # Skip levels too close to current price (spread protection)
            if abs(price - current_price) / current_price < 0.001:
                continue

            side = "SELL" if price > current_price else "BUY"

            # Amount logic
            # Buy Order: We need Quote (USDT). amount_per_grid is in USDT.
            # Sell Order: We need Base (BTC). amount_per_grid is in USDT value, so divide by price to get Qty.

            if side == "BUY":
                qty = bot.amount_per_grid / price
            else:
                # For Sell orders, we assume we want to hold 'amount_per_grid' WORth of asset at that price?
                # Or at current price?
                # Standard: amount_per_grid / current_price (Initial value)
                # Let's align with "Investment Amount" -> We bought X qty.
                qty = bot.amount_per_grid / current_price
                needed_base_asset += qty

            orders_to_place.append(
                {
                    "symbol": bot.pair,
                    "side": side,
                    "type": "LIMIT",
                    "quantity": round(qty, 6),  # TODO: Precision from exchange info
                    "price": round(price, 2),
                }
            )

        # 3. Rebalance (Buy required Base Asset)
        await self._ensure_base_balance(bot, needed_base_asset)

        logger.info(f"Bot {bot.id}: Placing {len(orders_to_place)} initial orders.")
        await self.order_manager.place_orders(bot.id, orders_to_place)

    async def _ensure_base_balance(self, bot: Bot, required_qty: float):
        """
        Checks if we have enough Coin (Base Asset). If not, Market Buy.
        """
        if required_qty <= 0:
            return

        base_asset = bot.pair.split("/")[0]  # e.g. BTC
        current_balance = await self.order_manager.exchange.get_balance(base_asset)

        logger.info(
            f"Bot {bot.id}: Rebalance Check. Need {required_qty} {base_asset}, Have {current_balance}"
        )

        if current_balance < required_qty:
            deficit = required_qty - current_balance
            # Buffer: Buy 1% extra to cover fees/movements? No, strict for now.
            logger.info(
                f"Bot {bot.id}: Rebalancing... Market Buying {deficit} {base_asset}"
            )

            try:
                await self.order_manager.exchange.create_order(
                    symbol=bot.pair,
                    side="BUY",
                    type="MARKET",
                    quantity=deficit,
                    price=None,
                    client_order_id=None,  # Market buys don't need strict tracking in grid? Or we track them?
                    # Better to track for PnL.
                )
                # Wait for fill? Market orders are usually instant.
                # ExchangeInterface async create_order returns dict with status using 'await', so it waits for API.
            except Exception as e:
                logger.error(f"Bot {bot.id}: Rebalance Market Buy Failed: {e}")
                raise  # Stop startup if we can't buy assets

    async def update_grid(self, bot: Bot, current_price: float):
        """
        Checks if orders need to be refilled (Buy Low -> Sell High logic).
        For V1: Simple implementation - if a level is hit (filled), place the opposite order.
        """
        # This requires knowing WHICH order was filled.
        # In the main loop, we sync orders. If an order becomes FILLED, we trigger this.
        pass  # To be implemented in next step if requested, or basic structure now.
