from abc import ABC, abstractmethod


class StrategyInterface(ABC):
    """
    Base class for future signal providers (RSI, MACD, etc).
    """

    @abstractmethod
    def get_signal(self, candle_data: list) -> str:
        """
        Analyzes candle data and returns a signal.
        Returns: 'BUY', 'SELL', or 'NEUTRAL'
        """
        pass

    @abstractmethod
    def should_stop_bot(self, current_price: float) -> bool:
        """
        Checks if a stopping condition is met (e.g., extreme market crash).
        """
        pass
