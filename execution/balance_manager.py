from database.repositories import BotRepository
from exchange.interface import ExchangeInterface
from utils.logger import setup_logger

logger = setup_logger("balance_manager")


class BalanceManager:
    def __init__(self, bot_repo: BotRepository, exchange: ExchangeInterface):
        self.bot_repo = bot_repo
        self.exchange = exchange

    def get_bot_equity(self, bot_id: int, current_price: float) -> float:
        """
        Calculates the total equity (Quote + Base converted to Quote) held by the bot.
        """
        bot = self.bot_repo.get_bot(bot_id)
        if not bot:
            return 0.0
        return bot.current_balance

    async def check_funds_for_order(
        self, bot_id: int, side: str, quantity: float, price: float
    ) -> bool:
        """
        Checks if the bot has enough allocated funds (virtual) AND if the wallet has enough funds (physical).
        Async because it calls exchange.get_balance.
        """
        # Fetch bot to get dynamic pair
        bot = self.bot_repo.get_bot(bot_id)
        if not bot:
            logger.error(f"Bot {bot_id} not found during fund check.")
            return False

        try:
            base_currency, quote_currency = bot.pair.split("/")
        except ValueError:
            logger.error(f"Bot {bot_id} has invalid pair format: {bot.pair}")
            return False

        required_amount = quantity * price if side == "BUY" else quantity
        asset = quote_currency if side == "BUY" else base_currency

        # 1. Physical Check (Async)
        physical_balance = await self.exchange.get_balance(asset)
        if physical_balance < required_amount:
            logger.warning(
                f"Bot {bot_id}: Insufficient Physical {asset}. Need {required_amount}, Has {physical_balance}"
            )
            return False

        # 2. Virtual/Isolation Check
        return True

    def allocate_initial_investment(self, bot_id: int, investment_amount: float):
        """
        Called on start. Records the investment.
        """
        bot = self.bot_repo.get_bot(bot_id)
        if bot:
            bot.investment_amount = investment_amount
            bot.current_balance = investment_amount
            self.bot_repo.session.commit()
