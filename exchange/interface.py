from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class ExchangeInterface(ABC):
    @abstractmethod
    async def get_ticker(self, symbol: str) -> Dict:
        """Returns {'symbol': str, 'price': float} via REST (fallback) or WS snapshot"""
        pass

    @abstractmethod
    async def watch_ticker(self, symbol: str) -> Dict:
        """Waits for next ticker update via WebSocket."""
        pass

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        side: str,
        type: str,
        quantity: float,
        price: float = None,
        client_order_id: str = None,
    ) -> Dict:
        """Places an order asynchronously."""
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancels an order asynchronously."""
        pass

    @abstractmethod
    async def cancel_all_orders(self, symbol: str) -> List[str]:
        """Cancels all orders for a symbol asynchronously."""
        pass

    @abstractmethod
    async def fetch_order(self, symbol: str, order_id: str) -> Dict:
        """Returns latest order status."""
        pass

    @abstractmethod
    async def fetch_open_orders(self, symbol: str) -> List[Dict]:
        """Returns list of open orders."""
        pass

    @abstractmethod
    async def get_balance(self, asset: str) -> float:
        """Returns free balance of asset."""
        pass

    @abstractmethod
    def price_to_precision(self, symbol: str, price: float) -> float:
        """Formats price according to exchange rules."""
        pass

    @abstractmethod
    def amount_to_precision(self, symbol: str, amount: float) -> float:
        """Formats amount according to exchange rules."""
        pass

    @abstractmethod
    async def close(self):
        """Closes the connection."""
        pass
