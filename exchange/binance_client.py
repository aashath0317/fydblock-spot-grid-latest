import ccxt.pro as ccxt  # IMPORTING PRO
from typing import Dict, List, Optional
from .interface import ExchangeInterface
import asyncio
from utils.logger import setup_logger

logger = setup_logger("binance_ws_client")


class BinanceClient(ExchangeInterface):
    def __init__(self, api_key: str, secret_key: str, testnet: bool = False):
        self.testnet = testnet
        self.api_key = api_key
        self.secret_key = secret_key
        self.client = None  # Lazy Init because async

    async def _init_client(self):
        if not self.client:
            self.client = ccxt.binance(
                {
                    "apiKey": self.api_key,
                    "secret": self.secret_key,
                    "enableRateLimit": True,
                    "options": {"defaultType": "spot"},
                }
            )
            if self.testnet:
                self.client.set_sandbox_mode(True)

    async def get_ticker(self, symbol: str) -> Dict:
        await self._init_client()
        try:
            # Prefer REST for one-off if WS is not established, but Pro supports fetchTicker too
            ticker = await self.client.fetch_ticker(symbol)
            return {"symbol": symbol, "price": ticker["last"]}
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            raise

    async def watch_ticker(self, symbol: str) -> Dict:
        await self._init_client()
        try:
            # Watches for the next ticker update (Real-time)
            ticker = await self.client.watch_ticker(symbol)
            return {"symbol": symbol, "price": float(ticker["last"])}
        except Exception as e:
            logger.error(f"Error watching ticker for {symbol}: {e}")
            raise

    async def create_order(
        self,
        symbol: str,
        side: str,
        type: str,
        quantity: float,
        price: float = None,
        client_order_id: str = None,
    ) -> Dict:
        await self._init_client()
        try:
            params = {}
            if client_order_id:
                params["newClientOrderId"] = client_order_id

            order = await self.client.create_order(
                symbol=symbol,
                type=type,
                side=side,
                amount=quantity,
                price=price,
                params=params,
            )
            return {
                "id": str(order["id"]),
                "client_order_id": order.get("clientOrderId"),
                "status": order["status"],
                "filled": float(order["filled"]),
                "remaining": float(order["remaining"]),
            }
        except Exception as e:
            logger.error(f"Error placing order {side} {symbol}: {e}")
            raise

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        await self._init_client()
        try:
            await self.client.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            logger.error(f"Error canceling order {order_id}: {e}")
            return False

    async def cancel_all_orders(self, symbol: str) -> List[str]:
        await self._init_client()
        try:
            orders = await self.client.cancel_all_orders(symbol)
            return [str(o["id"]) for o in orders]
        except Exception as e:
            logger.error(f"Error canceling all orders for {symbol}: {e}")
            return []

    async def fetch_order(self, symbol: str, order_id: str) -> Dict:
        await self._init_client()
        try:
            order = await self.client.fetch_order(order_id, symbol)
            return {
                "id": str(order["id"]),
                "client_order_id": order.get("clientOrderId"),
                "status": order["status"],
                "filled": float(order["filled"]),
                "remaining": float(order["remaining"]),
            }
        except Exception as e:
            logger.error(f"Error fetching order {order_id}: {e}")
            return {}

    async def fetch_open_orders(self, symbol: str) -> List[Dict]:
        await self._init_client()
        try:
            # Can switch to watch_orders for caching, but fetch is safer for reconciliation
            orders = await self.client.fetch_open_orders(symbol)
            return [
                {
                    "id": str(o["id"]),
                    "client_order_id": o.get("clientOrderId"),
                    "status": o["status"],
                    "price": float(o["price"]),
                    "side": o["side"],
                    "quantity": float(o["amount"]),
                }
                for o in orders
            ]
        except Exception as e:
            logger.error(f"Error fetching open orders for {symbol}: {e}")
            return []

    async def get_balance(self, asset: str) -> float:
        await self._init_client()
        try:
            balance = await self.client.fetch_balance()
            return float(balance[asset]["free"])
        except Exception as e:
            logger.error(f"Error fetching balance for {asset}: {e}")
            return 0.0

    async def close(self):
        if self.client:
            await self.client.close()
