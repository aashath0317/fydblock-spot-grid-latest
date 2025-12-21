import pandas as pd
from decimal import Decimal
from backtest.backtester import BacktestEngine


def verify_volume_logic():
    print("Verifying Volume Constraint Logic...")

    # 1. Setup Engine
    driver = BacktestEngine(
        initial_balance=Decimal("10000"), participation_rate=Decimal("0.1")
    )
    driver.grid_step = Decimal("1")  # Manually set step for counter-orders

    # 2. Setup Order: BUY 200 @ 100
    driver.orders.append(
        {"side": "BUY", "price": Decimal("100"), "qty": Decimal("200")}
    )

    # 3. Create Candle with Limit Volume
    # Price dips to 99 (activates limit), Volume = 1000
    # Max Fill = 1000 * 0.1 = 100
    row = {
        "timestamp": 1234567890,
        "open": 105,
        "high": 105,
        "low": 99,
        "close": 100,
        "volume": 1000,
    }

    print(f"Initial Order Qty: 200")
    print(f"Candle Volume: 1000 (Max Fill: 100)")

    # 4. Process
    driver.process_candle(row)

    # 5. Check Results
    if not driver.trades_history:
        print("FAIL: No trade generated.")
        return

    trade = driver.trades_history[0]
    print(f"Trade Qty: {trade['qty']} (Expected: 100)")

    if len(driver.orders) == 0:
        print("FAIL: Order was fully removed (Expected partial).")
    else:
        remaining_qty = driver.orders[0]["qty"]
        print(f"Remaining Order Qty: {remaining_qty} (Expected: 100)")

    if trade["qty"] == Decimal("100") and remaining_qty == Decimal("100"):
        print("SUCCESS: Partial fill logic verified.")
    else:
        print("FAIL: Quantities mismatch.")


if __name__ == "__main__":
    verify_volume_logic()
