import pandas as pd
from decimal import Decimal
from strategies.grid_math import calculate_grid_levels


class BacktestEngine:
    def __init__(
        self,
        initial_balance: Decimal = Decimal("1000.0"),
        maker_fee: Decimal = Decimal("0.001"),
        taker_fee: Decimal = Decimal("0.001"),
        participation_rate: Decimal = Decimal("0.1"),  # 10% of volume
    ):
        self.initial_balance = initial_balance
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.participation_rate = participation_rate
        self.balance = initial_balance
        self.asset_balance = Decimal("0.0")
        self.orders = []  # List of active dicts: {'price', 'side', 'qty'}
        self.trades_history = []
        self.grid_step = Decimal("0.0")

    def setup_grid(
        self,
        current_price: Decimal,
        lower_limit: Decimal,
        upper_limit: Decimal,
        grid_count: int,
        amount_per_grid: Decimal,
    ):
        self.orders = []
        self.lower_limit = lower_limit
        self.upper_limit = upper_limit
        self.grid_step = (upper_limit - lower_limit) / grid_count
        levels = calculate_grid_levels(lower_limit, upper_limit, grid_count)

        # Determine current position in grid?
        # Standard approach: Sell orders above, Buy orders below current price.

        for price in levels:
            if price > current_price:
                # Sell Order
                # Amount per grid (in USDT) / Current Price = Quantity (Base)
                qty = amount_per_grid / current_price

                self.orders.append({"side": "SELL", "price": price, "qty": qty})

                # Simulate "Rebalancing" (Market Buy) to fund this sell
                # Cost = qty * current_price (approx)
                cost = qty * current_price
                fee = cost * self.taker_fee  # Market buy fee

                self.balance -= cost + fee
                self.asset_balance += qty
            elif price < current_price:
                self.orders.append(
                    {"side": "BUY", "price": price, "qty": amount_per_grid / price}
                )

        # Fill 'Sell' side based on assumed initial buy?
        # For simple backtest, let's just assume we entered the market.

    def run(self, df: pd.DataFrame):
        for index, row in df.iterrows():
            self.process_candle(row)

        return self.generate_report()

    def process_candle(self, row):
        # Convert pandas/numpy flows to string then Decimal to avoid precision loss
        high = Decimal(str(row["high"]))
        low = Decimal(str(row["low"]))
        # Volume handling (default to infinite if missing)
        volume = Decimal(str(row.get("volume", "1000000000")))
        max_fill_avail = volume * self.participation_rate

        # Check Fills
        filled_indices = []
        new_orders = []

        for i, order in enumerate(self.orders):
            executed = False

            # Check Price Conditions
            if order["side"] == "BUY" and low <= order["price"]:
                executed = True
            elif order["side"] == "SELL" and high >= order["price"]:
                executed = True

            if executed:
                # VOLUME CHECK
                # How much can we really fill?
                fill_qty = min(order["qty"], max_fill_avail)

                # Check for Partial
                is_partial = fill_qty < order["qty"]

                if order["side"] == "BUY":
                    cost = order["price"] * fill_qty
                    fee = cost * self.maker_fee
                    self.balance -= cost + fee
                    self.asset_balance += fill_qty
                else:  # SELL
                    revenue = order["price"] * fill_qty
                    fee = revenue * self.maker_fee
                    self.balance += revenue - fee
                    self.asset_balance -= fill_qty

                self.trades_history.append(
                    {
                        "timestamp": row["timestamp"],
                        "side": order["side"],
                        "price": order["price"],
                        "qty": fill_qty,
                        "type": "partial" if is_partial else "fill",
                        "balance": self.balance
                        + (self.asset_balance * Decimal(str(row["close"]))),
                    }
                )

                # Counter Order (For the filled amount only)
                # We need to create a counter-order for 'fill_qty'
                # Note: _get_counter_order takes 'filled_order' dict.
                # We construct a temporary one.
                temp_filled = {
                    "side": order["side"],
                    "price": order["price"],
                    "qty": fill_qty,
                }
                counter_order = self._get_counter_order(temp_filled)
                if counter_order:
                    new_orders.append(counter_order)

                # Update Original Order
                if is_partial:
                    # Update quantity in place
                    self.orders[i]["qty"] -= fill_qty
                    # Do NOT add to filled_indices
                else:
                    # Full fill
                    filled_indices.append(i)

        # Remove filled
        for i in sorted(filled_indices, reverse=True):
            del self.orders[i]

        # Add new orders (Counter-orders)
        # We need the step size from setup_grid.
        # Since setup_grid didn't save it, let's recalculate or save it in init/setup.
        # For now, let's assume we can derive it or pass it.
        # Better: Store 'grid_step' in class.

        # NOTE: self.grid_step must be defined in setup_grid

        for order in new_orders:
            self.orders.append(order)

    def _get_counter_order(self, filled_order):
        step = self.grid_step
        if step <= 0:
            raise ValueError("Grid step is not initialized or invalid.")

        if filled_order["side"] == "BUY":
            # Buy Filled -> Place Sell High
            return {
                "side": "SELL",
                "price": filled_order["price"] + step,
                "qty": filled_order["qty"],
            }
        else:
            # Sell Filled -> Place Buy Low
            return {
                "side": "BUY",
                "price": filled_order["price"] - step,
                "qty": filled_order["qty"],
            }

    def generate_report(self):
        return {
            "final_balance": self.balance,  # Cash
            "asset_balance": self.asset_balance,
            "total_trades": len(self.trades_history),
        }
