from enum import Enum
import datetime
from database.models import Bot
from utils.logger import setup_logger

logger = setup_logger("auto_tuner")


class OptimizationAction(Enum):
    NONE = "NONE"
    RESET_UP = "RESET_UP"
    EXPAND_DOWN = "EXPAND_DOWN"


class AutoTuner:
    def __init__(self, cooldown_minutes: int = 30):
        self.cooldown_minutes = cooldown_minutes

    def check_adjustment(self, bot: Bot, current_price: float) -> OptimizationAction:
        """
        Determines if grid needs adjustment based on 'Auto' logic.
        """
        if bot.mode != "AUTO":
            return OptimizationAction.NONE

        # 1. Reset Up (Bullish Breakout)
        # Condition: Price breaks upper limit
        # Action: Immediate Reset
        if current_price > bot.upper_limit:
            logger.info(
                f"Bot {bot.id}: Price {current_price} > Upper {bot.upper_limit}. Triggering RESET_UP."
            )
            return OptimizationAction.RESET_UP

        # 2. Expand Down (Bearish Drop)
        # Condition: Price breaks lower limit
        if current_price < bot.lower_limit:
            # Check Cooldown
            last_update = bot.last_trailing_update
            if last_update:
                # Ensure timezone awareness compatibility
                # If last_update is naive, assume UTC. If aware, compare correctly.
                # Here assuming UTC for simplicity.
                now = datetime.datetime.utcnow()
                # Simple check:
                diff = (
                    now - last_update
                    if last_update.tzinfo is None
                    else datetime.datetime.now(datetime.timezone.utc) - last_update
                )

                if diff.total_seconds() < (self.cooldown_minutes * 60):
                    # Cooldown active
                    return OptimizationAction.NONE

            logger.info(
                f"Bot {bot.id}: Price {current_price} < Lower {bot.lower_limit}. Triggering EXPAND_DOWN."
            )
            return OptimizationAction.EXPAND_DOWN

        return OptimizationAction.NONE

    def calculate_new_params(
        self, bot: Bot, current_price: float, action: OptimizationAction
    ) -> dict:
        """
        Calculates new Lower/Upper limits based on action.
        """
        risk_percentage = (bot.risk_level or 10) / 100.0

        if action == OptimizationAction.RESET_UP:
            # Standard Reset: Center around current price
            # New range based on Original Risk %
            new_lower = current_price * (1 - risk_percentage)
            new_upper = current_price * (1 + risk_percentage)
            return {
                "lower_limit": new_lower,
                "upper_limit": new_upper,
                "grid_count": bot.grid_count,  # Keep same count or adjust density? Assume keep count.
            }

        elif action == OptimizationAction.EXPAND_DOWN:
            # Expand Logic:
            # Keep Upper Limit (or slightly adjust?) -> User said "upper grid line is same"
            # Lower Limit -> Decrease significantly

            # How much to lower?
            # Strategy: Add another "block" of grid below.
            # Or use risk percentage relative to current price to find new bottom.

            # Let's define new bottom as: Current Price - (Current Price * Risk%)
            # This ensures we cover the dip.
            new_lower = current_price * (1 - risk_percentage)

            # Ensure new lower is actually lower than old lower
            if new_lower >= bot.lower_limit:
                new_lower = (
                    bot.lower_limit * 0.95
                )  # Force 5% drop if calculated is too close

            return {
                "lower_limit": new_lower,
                "upper_limit": bot.upper_limit,  # Keep Upper
                "grid_count": bot.grid_count,  # Keep count same -> Wider gaps (Density decreases)
            }

        return {}
