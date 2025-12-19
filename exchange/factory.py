from .interface import ExchangeInterface
from .binance_client import BinanceClient


class ExchangeFactory:
    @staticmethod
    def create_exchange(
        exchange_name: str, api_key: str, secret_key: str, testnet: bool = False
    ) -> ExchangeInterface:
        if exchange_name.lower() == "binance":
            return BinanceClient(api_key, secret_key, testnet)
        else:
            raise ValueError(f"Exchange {exchange_name} not supported.")
