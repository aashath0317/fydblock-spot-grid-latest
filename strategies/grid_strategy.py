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

    async def update_grid(self, bot: Bot, filled_orders: List[dict]):
        """
        Reacts to filled orders by placing the counter-order.
        Buy Low at Price X -> Place Sell High at Price X + Step
        Sell High at Price Y -> Place Buy Low at Price Y - Step
        """
        if not filled_orders:
            return

        # Calculate Grid Step
        # Assuming Arithmetic for V1 MVP
        # Step = (Upper - Lower) / Count
        step = (bot.upper_limit - bot.lower_limit) / bot.grid_count

        orders_to_place = []

        for filled in filled_orders:
            # Logic:
            # If we bought at 50000, we want to sell at 50000 + step.
            # If we sold at 50100, we want to buy back at 50100 - step.

            new_side = "SELL" if filled["side"] == "BUY" else "BUY"

            # TODO: Handle Geometric logic here if needed check bot.grid_type (not in V1 model yet, defaults arithmetic)

            if new_side == "SELL":
                new_price = filled["price"] + step
            else:
                new_price = filled["price"] - step

            # Validation
            if new_price > bot.upper_limit or new_price < bot.lower_limit:
                logger.warning(
                    f"Bot {bot.id}: Counter-order price {new_price} out of bounds. Skipping."
                )
                continue

            # Qty Logic:
            # Keep same Quantity (Fixed Base) or Keep same Value?
            # Standard Grid: Buy 0.01 BTC, Sell 0.01 BTC. (Base Asset Preservation)
            qty = filled["quantity"]

            # Margin for Profit?
            # If we buy 0.01 at 50k, cost 500.
            # Sell 0.01 at 51k, get 510. Profit 10 USDT.
            # This works.

            # Check Balance?
            # If we sold, we have USDT to buy back.
            # If we bought, we have BTC to sell.
            # So theoretically we always have funds.

            orders_to_place.append(
                {
                    "symbol": bot.pair,
                    "side": new_side,
                    "type": "LIMIT",
                    "quantity": qty,
                    "price": round(new_price, 2),
                }
            )

        if orders_to_place:
            logger.info(f"Bot {bot.id}: Placing {len(orders_to_place)} counter-orders.")
            await self.order_manager.place_orders(bot.id, orders_to_place)
