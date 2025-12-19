import pandas as pd
from datetime import datetime
from typing import List, Dict


class HistoricalDataLoader:
    def __init__(self, data_source: str = "csv"):
        self.data_source = data_source

    def load_from_csv(self, file_path: str) -> pd.DataFrame:
        """
        Expects CSV with columns: check_open, high, low, close, volume, timestamp
        """
        try:
            df = pd.read_csv(file_path)
            # Standardize columns
            df.columns = [c.lower() for c in df.columns]
            required = ["timestamp", "open", "high", "low", "close"]
            if not all(col in df.columns for col in required):
                raise ValueError(f"CSV missing required columns: {required}")

            # Parse timestamp if string
            if df["timestamp"].dtype == object:
                df["timestamp"] = pd.to_datetime(df["timestamp"])

            return df
        except Exception as e:
            print(f"Error loading CSV: {e}")
            return pd.DataFrame()

    def load_dummy_data(self) -> pd.DataFrame:
        """Generates sine wave price data for testing."""
        import numpy as np

        dates = pd.date_range(start="2024-01-01", periods=1000, freq="1H")
        price = 50000 + 1000 * np.sin(np.linspace(0, 50, 1000))

        df = pd.DataFrame(
            {
                "timestamp": dates,
                "open": price,
                "high": price + 50,
                "low": price - 50,
                "close": price,  # Simplify close=open for dummy
            }
        )
        return df
