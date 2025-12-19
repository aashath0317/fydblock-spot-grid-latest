import pandas as pd
from typing import List, Dict
from strategies.grid_math import calculate_grid_levels


class BacktestEngine:
    def __init__(
        self,
        initial_balance: float = 1000.0,
        maker_fee: float = 0.001,
        taker_fee: float = 0.001,
    ):
        self.initial_balance = initial_balance
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.balance = initial_balance
        self.asset_balance = 0.0
        self.orders = []  # List of active dicts: {'price', 'side', 'qty'}
        self.trades_history = []

    def setup_grid(
        self,
        current_price: float,
        lower_limit: float,
        upper_limit: float,
        grid_count: int,
        amount_per_grid: float,
    ):
        self.orders = []
        self.grid_step = (upper_limit - lower_limit) / grid_count
        levels = calculate_grid_levels(lower_limit, upper_limit, grid_count)

        # Determine current position in grid?
        # Standard approach: Sell orders above, Buy orders below current price.

        for price in levels:
            if price > current_price:
                # Sell Order
                # Need assets to place sell order? In backtest, we assume we might have them or start fresh.
                # If starting fresh with USDT, we can't place sells yet unless we buy first.
                # Simplification: Allow "short" or assume mixed startup.
                # Strict: Only place Buys first.
                pass
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
        high = row["high"]
        low = row["low"]

        # Check Fills
        filled_indices = []
        new_orders = []

        for i, order in enumerate(self.orders):
            executed = False
            if order["side"] == "BUY" and low <= order["price"]:
                # Buy Filled
                cost = order["price"] * order["qty"]
                fee = cost * self.maker_fee
                self.balance -= cost + fee
                self.asset_balance += order["qty"]
                executed = True

                # Place Sell Grid above
                new_orders.append(self._get_counter_order(order))

            elif order["side"] == "SELL" and high >= order["price"]:
                # Sell Filled
                revenue = order["price"] * order["qty"]
                fee = revenue * self.maker_fee
                self.balance += revenue - fee
                self.asset_balance -= order["qty"]
                executed = True

                # Place Buy Grid below
                new_orders.append(self._get_counter_order(order))

            if executed:
                filled_indices.append(i)
                self.trades_history.append(
                    {
                        "timestamp": row["timestamp"],
                        "side": order["side"],
                        "price": order["price"],
                        "qty": order["qty"],
                        "balance": self.balance + (self.asset_balance * row["close"]),
                    }
                )

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
