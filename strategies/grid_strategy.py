from typing import List, Optional
import asyncio
from decimal import Decimal
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

    async def place_initial_grid(self, bot: Bot, current_price: Decimal):
        """
        Calculates grid levels, rebalances portfolio, and places OPEN orders.
        """
        logger.info(f"Bot {bot.id}: Calculating initial grid...")

        # 1. Calc Levels
        levels = calculate_grid_levels(
            bot.lower_limit,
            bot.upper_limit,
            bot.grid_count,
            getattr(bot, "grid_type", "ARITHMETIC"),
        )

        orders_to_place = []
        needed_base_asset = Decimal("0")

        # 2. Plan Orders
        for price in levels:
            # Skip levels too close to current price (spread protection)
            if abs(price - current_price) / current_price < Decimal("0.001"):
                continue

            # Standardize Base Asset Quantity (Support Shifting)
            # 1. Determine Base Qty per Grid
            if bot.quantity_type == "BASE":
                base_qty = bot.amount_per_grid
            else:  # QUOTE
                # Use Current Price as reference for "Value"
                # This locks in static base volume for the grid duration
                base_qty = bot.amount_per_grid / current_price

            needed_base_asset += base_qty

            side = "SELL" if price > current_price else "BUY"

            orders_to_place.append(
                {
                    "symbol": bot.pair,
                    "side": side,
                    "type": "LIMIT",
                    "quantity": self.order_manager.exchange.amount_to_precision(
                        bot.pair, base_qty
                    ),
                    "price": self.order_manager.exchange.price_to_precision(
                        bot.pair, price
                    ),
                }
            )

        # 3. Rebalance (Buy required Base Asset)
        await self._ensure_base_balance(bot, needed_base_asset)

        logger.info(f"Bot {bot.id}: Placing {len(orders_to_place)} initial orders.")
        await self.order_manager.place_orders(bot.id, orders_to_place)

    async def _ensure_base_balance(self, bot: Bot, required_qty: Decimal):
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

            # Limit Order with Buffer (Marketable Limit Implementation)
            # Provides protection against infinite slippage.
            ticker = await self.order_manager.exchange.get_ticker(bot.pair)
            current_price = ticker["price"]
            limit_price = current_price * Decimal("1.02")  # 2% Slippage tolerance

            # Convert to precision string
            limit_price_str = self.order_manager.exchange.price_to_precision(
                bot.pair, limit_price
            )
            quantity_str = self.order_manager.exchange.amount_to_precision(
                bot.pair, deficit
            )

            logger.info(f"Bot {bot.id}: Rebalancing via LIMIT Buy @ {limit_price_str}")

            try:
                order_response = await self.order_manager.exchange.create_order(
                    symbol=bot.pair,
                    side="BUY",
                    type="LIMIT",
                    quantity=quantity_str,
                    price=limit_price_str,
                    client_order_id=None,
                )

                # Polling for Fill (Prevent Race Condition)
                # We expect immediate fill for marketable limit.
                order_id = order_response.get("id")
                if not order_id:
                    # Should not happen with CCXT
                    logger.warning(
                        f"Bot {bot.id}: Rebalance order created but no ID returned."
                    )
                else:
                    for _ in range(20):  # Wait up to 20 * 0.5 = 10 seconds
                        order_info = await self.order_manager.exchange.fetch_order(
                            bot.pair, order_id
                        )
                        status = order_info.get("status")
                        if status == "closed":  # CCXT uses 'closed' for filled
                            logger.info(
                                f"Bot {bot.id}: Rebalance order {order_id} FILLED."
                            )
                            break
                        elif status == "canceled" or status == "rejected":
                            raise Exception(f"Rebalance order {status}")

                        await asyncio.sleep(0.5)
                    else:
                        # Timeout
                        logger.error(
                            f"Bot {bot.id}: Rebalance order {order_id} timed out (not filled in 10s). Canceling..."
                        )

                        try:
                            await self.order_manager.exchange.cancel_order(
                                bot.pair, order_id
                            )
                        except Exception as cancel_error:
                            logger.error(
                                f"Bot {bot.id}: Failed to cancel timed-out rebalance order: {cancel_error}"
                            )

                        # Proceed? Or Fail? If we proceed, we risk error. Fail is safer.
                        raise Exception("Rebalance order timed out and was canceled.")
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
        # Calculate Grid Step or Ratio
        grid_type = getattr(bot, "grid_type", "ARITHMETIC")

        if grid_type == "GEOMETRIC":
            # ratio = (Upper / Lower)^(1/(N-1))
            ratio = (bot.upper_limit / bot.lower_limit) ** (
                Decimal("1") / (bot.grid_count - 1)
            )
        else:
            step = (bot.upper_limit - bot.lower_limit) / bot.grid_count

        orders_to_place = []

        for filled in filled_orders:
            # 1. Check for Shifting Grid condition (Top Sell Filled)
            # Use epsilon for float comparison logic
            # If we sold at something >= Upper Limit (approx)
            if filled["side"] == "SELL" and filled["price"] >= (
                bot.upper_limit * Decimal("0.999")
            ):
                if self.bot_repo:
                    # SHIFT LOGIC (Does it need to handle Geometric? For V1 assuming Arithmetic Shift Logic or generic step?)
                    # Shift logic relies on "Step". For Geometric, "Step" changes.
                    # Geometric shifting is complex (requires scaling limits by Ratio).
                    # For now, we will calculate "Local Step" for the shift function if needed,
                    # OR we just pass the Ratio and update Shift logic?
                    # Simplest V1: Use current local step at Top.
                    # shift_step = upper_limit * (ratio - 1)
                    if grid_type == "GEOMETRIC":
                        shift_step = bot.upper_limit * (ratio - Decimal("1"))
                    else:
                        shift_step = step

                    logger.info(f"Bot {bot.id}: Top Sell Hit! Shifting Grid Up.")
                    await self._shift_grid_up(bot, shift_step, filled)
                    continue
                else:
                    logger.warning(
                        "Bot {bot.id}: Top Sell Hit, but no BotRepo available to shift. Placing normal counter-order."
                    )

            # Logic:
            # Snap to grid index to prevent drift.

            if grid_type == "GEOMETRIC":
                # Index = ln(Price / Lower) / ln(Ratio)
                distance_ratio = filled["price"] / bot.lower_limit
                exact_index = distance_ratio.ln() / ratio.ln()
                grid_index = int(
                    exact_index.to_integral_value(rounding="ROUND_HALF_UP")
                )

                if filled["side"] == "BUY":
                    new_side = "SELL"
                    new_index = grid_index + 1
                else:
                    new_side = "BUY"
                    new_index = grid_index - 1

                new_price = bot.lower_limit * (ratio**new_index)

            else:  # ARITHMETIC
                distance = filled["price"] - bot.lower_limit
                exact_index = distance / step
                # Round to nearest integer index
                grid_index = int(
                    exact_index.to_integral_value(rounding="ROUND_HALF_UP")
                )

                if filled["side"] == "BUY":
                    # Bought at Index i (Low). Sell at Index i+1 (High).
                    new_side = "SELL"
                    new_index = grid_index + 1
                else:
                    # Sold at Index i (High). Buy at Index i-1 (Low).
                    new_side = "BUY"
                    new_index = grid_index - 1

                new_price = bot.lower_limit + (step * new_index)

            # Validation
            if new_price > (bot.upper_limit * Decimal("1.001")) or new_price < (
                bot.lower_limit * Decimal("0.999")
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
                    "quantity": self.order_manager.exchange.amount_to_precision(
                        bot.pair, qty
                    ),
                    "price": self.order_manager.exchange.price_to_precision(
                        bot.pair, new_price
                    ),
                }
            )

        if orders_to_place:
            logger.info(f"Bot {bot.id}: Placing {len(orders_to_place)} counter-orders.")
            await self.order_manager.place_orders(bot.id, orders_to_place)

    async def _shift_grid_up(self, bot: Bot, step: Decimal, filled_order: dict):
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
        # Assuming list of Order objects
        found_bottom = False

        if open_orders:
            # Filter for Buy Orders
            buy_orders = [o for o in open_orders if o.side == "BUY"]

            if buy_orders:
                # Identify the bottom order by lowest price
                lowest_buy = min(buy_orders, key=lambda o: o.price)

                # Check if reasonable? It should be near old_lower.
                # But trusting min() is robust for Shift Up.
                logger.info(
                    f"Bot {bot.id}: Cancelling bottom order {lowest_buy.client_order_id} @ {lowest_buy.price}"
                )
                try:
                    await self.order_manager.exchange.cancel_order(
                        bot.pair, lowest_buy.exchange_order_id
                    )
                    await self.order_manager.order_repo.update_status(
                        lowest_buy.client_order_id, "CANCELED"
                    )
                    found_bottom = True
                except Exception as e:
                    logger.error(f"Bot {bot.id}: Failed to cancel bottom order: {e}")
                    # ABORT SHIFT to prevent phantom orders
                    return
            else:
                logger.warning(
                    f"Bot {bot.id}: No BUY orders found to cancel for shift."
                )

        if not found_bottom:
            logger.warning(
                f"Bot {bot.id}: Could not find bottom buy order to cancel at {old_lower}"
            )
            # Proceed anyway? If we don't cancel, we might have extra orders.
            # But we must shift limits.
            # NO: User requirement is to prevent Phantom Orders and desync.
            # If we didn't cancel the bottom, we shouldn't add a top.
            return

        # 2. (Deferred) Update Limits in DB
        # moved to end

        # 3. Buy Replenishment & 4. Place New Top Sell
        try:
            # We sold X at Top. We need X to place new Top Sell.
            # We have USDT from the sale.
            qty_needed = filled_order["quantity"]
            logger.info(
                f"Bot {bot.id}: Replenishing {qty_needed} {bot.pair} via MARKET BUY."
            )

            # Safe Replenishment (Limit Buy)
            ticker = await self.order_manager.exchange.get_ticker(bot.pair)
            current_price = ticker["price"]
            limit_price = current_price * Decimal("1.02")

            limit_price_str = self.order_manager.exchange.price_to_precision(
                bot.pair, limit_price
            )
            quantity_str = self.order_manager.exchange.amount_to_precision(
                bot.pair, qty_needed
            )

            await self.order_manager.exchange.create_order(
                symbol=bot.pair,
                side="BUY",
                type="LIMIT",
                quantity=quantity_str,
                price=limit_price_str,
                client_order_id=None,
            )

            # 4. Place New Top Sell
            # At new_upper
            new_top_order = {
                "symbol": bot.pair,
                "side": "SELL",
                "type": "LIMIT",
                "quantity": self.order_manager.exchange.amount_to_precision(
                    bot.pair, qty_needed
                ),
                "price": self.order_manager.exchange.price_to_precision(
                    bot.pair, new_upper
                ),
            }

            logger.info(f"Bot {bot.id}: Placing new TOP SELL @ {new_upper}")
            await self.order_manager.place_orders(bot.id, [new_top_order])

        except Exception as e:
            logger.error(
                f"Bot {bot.id}: Shift Transaction Failed: {e}. Attempting ROLLBACK."
            )

            # ROLLBACK: Re-create the canceled bottom buy
            # lowest_buy object still holds data
            try:
                rollback_order = {
                    "symbol": bot.pair,
                    "side": "BUY",
                    "type": "LIMIT",
                    "quantity": self.order_manager.exchange.amount_to_precision(
                        bot.pair, lowest_buy.quantity
                    ),
                    "price": self.order_manager.exchange.price_to_precision(
                        bot.pair, lowest_buy.price
                    ),
                }
                logger.info(
                    f"Bot {bot.id}: ROLLBACK - Re-placing Bottom Buy @ {lowest_buy.price}"
                )
                await self.order_manager.place_orders(bot.id, [rollback_order])
                # We do NOT update limits. We return to previous state.
                logger.info(
                    f"Bot {bot.id}: ROLLBACK SUCCESSFUL. Grid returned to safety."
                )
            except Exception as rollback_error:
                logger.critical(
                    f"Bot {bot.id}: ROLLBACK FAILED! Grid is compromised. Error: {rollback_error}"
                )

            return  # Exit Shift

        # 5. COMMIT: Update Limits in DB
        # Only reached if exchange ops succeeded
        if self.bot_repo:
            await self.bot_repo.update_grid_config(
                bot.id,
                {
                    "lower_limit": new_lower,
                    "upper_limit": new_upper,
                },
            )
            logger.info(
                f"Bot {bot.id}: Shifted limits locally and in DB to [{new_lower}, {new_upper}]"
            )
