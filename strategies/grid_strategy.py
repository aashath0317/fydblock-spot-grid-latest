from typing import List, Dict, Optional
from execution.order_manager import OrderManager
from strategies.grid_math import calculate_grid_levels
from database.models import Bot
from database.repositories import BotRepository
from utils.logger import setup_logger

logger = setup_logger("grid_strategy")


class GridStrategy:
    def __init__(
        self, order_manager: OrderManager, bot_repo: Optional[BotRepository] = None
    ):
        self.order_manager = order_manager
        self.bot_repo = bot_repo

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

            if side == "BUY":
                if bot.quantity_type == "BASE":
                    # Buy X amount of base. Cost = X * Price.
                    qty = bot.amount_per_grid
                else:  # QUOTE
                    qty = bot.amount_per_grid / price
            else:
                # SELL side
                if bot.quantity_type == "BASE":
                    qty = bot.amount_per_grid
                else:
                    # Original logic was amount_per_grid / current_price?
                    # No, if we want fixed Quote value, we sell whatever equals that Value?
                    # "Fixed Quote" usually means "Invest 10 USDT per grid".
                    # So if Price is 100, we buy 0.1. If we sell at 100, we sell 0.1.
                    # If we sell at 110? We sell X such that X * 110 = 10? No, usually Grid holds fixed Base for Sells?
                    # Let's stick to standard behavior:
                    # If QUOTE mode: Qty = Value / Price.
                    qty = bot.amount_per_grid / (
                        price if side == "BUY" else current_price
                    )

                needed_base_asset += qty

            orders_to_place.append(
                {
                    "symbol": bot.pair,
                    "side": side,
                    "type": "LIMIT",
                    "quantity": float(
                        self.order_manager.exchange.amount_to_precision(bot.pair, qty)
                    ),
                    "price": float(
                        self.order_manager.exchange.price_to_precision(bot.pair, price)
                    ),
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
        step = (bot.upper_limit - bot.lower_limit) / bot.grid_count

        orders_to_place = []

        for filled in filled_orders:
            # 1. Check for Shifting Grid condition (Top Sell Filled)
            # Use epsilon for float comparison logic
            # If we sold at something >= Upper Limit (approx)
            if filled["side"] == "SELL" and filled["price"] >= (
                bot.upper_limit * 0.999
            ):
                if self.bot_repo:
                    logger.info(f"Bot {bot.id}: Top Sell Hit! Shifting Grid Up.")
                    await self._shift_grid_up(bot, step, filled)
                    continue
                else:
                    logger.warning(
                        "Bot {bot.id}: Top Sell Hit, but no BotRepo available to shift. Placing normal counter-order."
                    )

            # Logic:
            # If we bought at 50000, we want to sell at 50000 + step.
            # If we sold at 50100, we want to buy back at 50100 - step.

            new_side = "SELL" if filled["side"] == "BUY" else "BUY"

            if new_side == "SELL":
                new_price = filled["price"] + step
            else:
                new_price = filled["price"] - step

            # Validation
            if new_price > (bot.upper_limit * 1.001) or new_price < (
                bot.lower_limit * 0.999
            ):
                logger.warning(
                    f"Bot {bot.id}: Counter-order price {new_price} out of bounds [{bot.lower_limit}, {bot.upper_limit}]. Skipping."
                )
                continue

            # Qty Logic:
            qty = filled["quantity"]

            orders_to_place.append(
                {
                    "symbol": bot.pair,
                    "side": new_side,
                    "type": "LIMIT",
                    "quantity": float(
                        self.order_manager.exchange.amount_to_precision(bot.pair, qty)
                    ),
                    "price": float(
                        self.order_manager.exchange.price_to_precision(
                            bot.pair, new_price
                        )
                    ),
                }
            )

        if orders_to_place:
            logger.info(f"Bot {bot.id}: Placing {len(orders_to_place)} counter-orders.")
            await self.order_manager.place_orders(bot.id, orders_to_place)

    async def _shift_grid_up(self, bot: Bot, step: float, filled_order: dict):
        """
        Shifts the grid up by one 'step'.
        1. Cancel Bottom Buy.
        2. Update Limits in DB.
        3. Buy Replenishment (Market).
        4. Place New Top Sell.
        """
        old_lower = bot.lower_limit
        new_lower = old_lower + step
        new_upper = bot.upper_limit + step

        # 1. Cancel Bottom Buy
        # Find order close to old_lower
        open_orders = await self.order_manager.order_repo.get_open_orders(bot.id)
        # Assuming list of Order objects
        found_bottom = False
        import math

        for order in open_orders:
            if order.side == "BUY" and math.isclose(
                order.price, old_lower, rel_tol=0.001
            ):
                logger.info(
                    f"Bot {bot.id}: Cancelling bottom order {order.client_order_id} @ {order.price}"
                )
                # Cancel via exchange
                try:
                    await self.order_manager.exchange.cancel_order(
                        bot.pair, order.exchange_order_id
                    )
                    await self.order_manager.order_repo.update_status(
                        order.client_order_id, "CANCELED"
                    )
                    found_bottom = True
                except Exception as e:
                    logger.error(f"Bot {bot.id}: Failed to cancel bottom order: {e}")
                break

        if not found_bottom:
            logger.warning(
                f"Bot {bot.id}: Could not find bottom buy order to cancel at {old_lower}"
            )
            # Proceed anyway? If we don't cancel, we might have extra orders.
            # But we must shift limits.

        # 2. Update Limits in DB
        # We need to update the passed 'bot' object AND the DB
        bot.lower_limit = new_lower
        bot.upper_limit = new_upper
        # bot is attached to session handled by main loop?
        # main loop uses `async with db.get_session()`.
        # `bot` was fetched there. Changes to `bot` should track.
        # But we need to flush/commit.
        # Since we don't control the session commit here without repo.
        # `self.bot_repo` has access to session?
        # `BotRepository` has `self.session`.
        if self.bot_repo:
            await self.bot_repo.session.flush()  # Or update explicitly
            # Better: use repo method to update specific fields to ensure cleanliness?
            # Or just `session.commit()`?
            # Creating a dedicated update method is safer.
            # But let's try direct commit if we trust session attachment.
            await self.bot_repo.update_grid_config(
                bot.id,
                {
                    "lower_limit": new_lower,
                    "upper_limit": new_upper,
                    # "grid_count": bot.grid_count # Unchanged
                },
            )
            logger.info(f"Bot {bot.id}: Shifted limits to [{new_lower}, {new_upper}]")

        # 3. Buy Replenishment
        # We sold X at Top. We need X to place new Top Sell.
        # We have USDT from the sale.
        qty_needed = filled_order["quantity"]
        logger.info(
            f"Bot {bot.id}: Replenishing {qty_needed} {bot.pair} via MARKET BUY."
        )

        try:
            await self.order_manager.exchange.create_order(
                symbol=bot.pair,
                side="BUY",
                type="MARKET",
                quantity=qty_needed,
                price=None,
                client_order_id=None,  # We can track it if we want logs, but Market usually fills instantly.
            )
            # Log trade? OrderManager usually handles this if we go through it.
            # But here we went direct to exchange. Ideally, create a DB order for tracking?
            # For simplicity in V1, we skip DB tracking for rebalance/replenish market orders,
            # OR we should implement it properly.
            # Let's just log it.
        except Exception as e:
            logger.error(f"Bot {bot.id}: Replenishment Failed: {e}")
            # Vital failure?

        # 4. Place New Top Sell
        # At new_upper

        new_top_order = {
            "symbol": bot.pair,
            "side": "SELL",
            "type": "LIMIT",
            "quantity": float(
                self.order_manager.exchange.amount_to_precision(bot.pair, qty_needed)
            ),
            "price": float(
                self.order_manager.exchange.price_to_precision(bot.pair, new_upper)
            ),
        }

        logger.info(f"Bot {bot.id}: Placing new TOP SELL @ {new_upper}")
        await self.order_manager.place_orders(bot.id, [new_top_order])
