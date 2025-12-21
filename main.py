from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Literal
import uvicorn
import asyncio
import datetime
from contextlib import asynccontextmanager

# Internal modules
from database.db_manager import db
from database.repositories import BotRepository, OrderRepository, TradeRepository
from execution.order_manager import OrderManager
from exchange.factory import ExchangeFactory
from strategies.auto_tuner import AutoTuner, OptimizationAction
from strategies.grid_strategy import GridStrategy
from utils.logger import setup_logger
from utils.health import health_system

from utils.security import decrypt_value

logger = setup_logger("main_api")


# --- Schemas ---
class BotCreate(BaseModel):
    user_id: str
    pair: str
    amount: float
    lower_limit: float
    upper_limit: float
    grid_count: int
    quantity_type: Literal["QUOTE", "BASE"] = "QUOTE"
    mode: Literal["AUTO", "MANUAL"] = "MANUAL"
    risk_level: Optional[int] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    api_key: str
    secret_key: str


class BotID(BaseModel):
    bot_id: int


# --- Global State ---
active_bots = {}  # bot_id -> {'task': Task, 'exchange': ExchangeInterface}


async def bot_loop(bot_id: int, exchange_api):
    """
    Real-time WebSocket Loop.
    """
    logger.info(f"Bot {bot_id}: Async WS Loop started.")

    # Create persistent session for the loop (or transient, but persistent is easier for now)
    # WARNING: Long-lived sessions can be problematic. Better to create per-tick or per-action.
    # BUT OrderManager is stateful with Repo?
    # Repo is stateless, just holds session. OrderManager is mostly stateless.
    # Let's instantiate OrderManager with a session that we close on exit?
    # Actually, proper way:
    #
    # while True:
    #    async with db.get_session() as session:
    #         # do work

    # However, `watch_ticker` blocks. We don't want to hold session open while waiting for price.
    #
    # Refactor:
    # Loop waits for Price.
    # ON Price:
    #   Open Session -> Sync -> Grid Logic -> Close Session.

    try:
        # Initial boot check order sync

        # === PERSISTENT OBJECTS ===
        # Instantiate once. Repos updated per-tick.
        # We start with None repos.
        order_manager = OrderManager(exchange_api)
        grid_strategy = GridStrategy(order_manager)
        auto_tuner = AutoTuner()

        # Initial Sync (if needed before loop, do it with fresh session)
        async with db.get_session() as session:
            order_manager.order_repo = OrderRepository(session)
            order_manager.trade_repo = TradeRepository(session)
            await order_manager.sync_orders(bot_id)

        while True:
            # A. Watch for Price Update (Real-time Blocking until update)
            try:
                # 1. Get Bot Pair (Quick session or cache?)
                # To minimize DB spam, maybe cache pair? But safe to read.
                async with db.get_session() as session:
                    bot = await BotRepository(session).get_bot(bot_id)

                if not bot:
                    break

                pair = bot.pair  # Extract before loop? Pair shouldn't change.

                # Wait for ticker (No DB involvement)
                ticker = await exchange_api.watch_ticker(pair)
                current_price = ticker["price"]

                # B. Health Heartbeat
                health_system.heartbeat()

                # Critical: Stop Loss Check
                if bot.stop_loss and current_price <= bot.stop_loss:
                    logger.critical(
                        f"Bot {bot_id}: STOP LOSS HIT ({current_price} <= {bot.stop_loss}). STOPPING BOT."
                    )
                    # We need a session to update status.
                    async with db.get_session() as sl_session:
                        # Cancel all
                        # We need managers initialized? They are persistent.
                        # We can use order_manager directly with sl_session injection?
                        # Or just use them as is if they don't depend on session for cancellation (they usually use exchange).
                        # cancel_bot_orders uses order_repo.get_open_orders which needs session.
                        # So we need to inject session.
                        order_manager.order_repo = OrderRepository(sl_session)
                        await order_manager.cancel_bot_orders(bot_id)

                        await BotRepository(sl_session).update_status(bot_id, "STOPPED")
                    break

                # C. Logic (Requires DB)
                async with db.get_session() as session:
                    # Re-instantiate Repos for this UOW
                    # CRITICAL FIX: Re-fetch bot to attach to this session (prevents DetachedInstanceError)
                    bot_repo = BotRepository(session)
                    bot = await bot_repo.get_bot(bot_id)
                    if not bot:
                        logger.warning(f"Bot {bot_id} not found in logic loop.")
                        break

                    # Update Persistent Managers with Fresh Repos attached to this session
                    order_manager.order_repo = OrderRepository(session)
                    order_manager.trade_repo = TradeRepository(session)
                    grid_strategy.bot_repo = bot_repo

                    # 1. Sync Orders
                    filled_orders = await order_manager.sync_orders(bot_id)

                    # 2. Grid Logic
                    if filled_orders:
                        # we need 'bot' object attached to this session or re-fetched?
                        # 'bot' from above is detached. 'grid_strategy' might need fresh bot if it writes to it?
                        # update_grid reads bot limits.
                        # If it doesn't write to bot, detached is fine.
                        await grid_strategy.update_grid(bot, filled_orders)

                    # 3. Auto Tune
                    action = auto_tuner.check_adjustment(bot, current_price)
                    if action != OptimizationAction.NONE:
                        logger.info(f"Bot {bot_id}: AutoTuner triggered {action.value}")

                        # a. Calculate New Params
                        new_params = auto_tuner.calculate_new_params(
                            bot, current_price, action
                        )
                        if new_params:
                            # b. Cancel All Orders
                            logger.info(
                                f"Bot {bot_id}: Cancelling orders for re-grid..."
                            )
                            await order_manager.cancel_bot_orders(bot_id)

                            # c. Update Bot Config in DB
                            # We need to use the Repo attached to this session
                            # bot_repo already exists in this scope
                            updated_bot = await bot_repo.update_grid_config(
                                bot_id, new_params
                            )

                            # d. Re-Place Grid
                            logger.info(f"Bot {bot_id}: Placing new grid...")
                            # Note: updated_bot is attached to session, ready to use.
                            await grid_strategy.place_initial_grid(
                                updated_bot, current_price
                            )

                            # e. Update Trailing Timestamp (to prevent rapid-fire expansion)
                            if action == OptimizationAction.EXPAND_DOWN:
                                # We need to set 'last_trailing_update'
                                # Assuming model has this field (SRS said it should).
                                # If not in model yet, we might need to add it or fail gracefully.
                                # Let's check model?
                                # For now, update if attribute exists.
                                updated_bot.last_trailing_update = (
                                    datetime.datetime.utcnow()
                                )
                                await session.commit()

            except Exception as e:
                logger.critical(
                    f"Bot {bot_id} Loop Error: {e}"
                )  # Upgraded to Critical for Alerting
                health_system.log_error()
                # TODO: Send Webhook/Email
                await asyncio.sleep(5)  # Backoff on error

    except asyncio.CancelledError:
        logger.info(f"Bot {bot_id}: Loop cancelled.")
        await exchange_api.close()
    except Exception as e:
        logger.critical(f"Bot {bot_id}: Fatal Crash: {e}")
        health_system.log_error()


# --- Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    logger.info("System Startup: DB Initialized.")

    # 2. Restart Logic
    async with db.get_session() as session:
        repo = BotRepository(session)
        running_bots = await repo.get_running_bots()

        if running_bots:
            logger.info(f"System Startup: Resuming {len(running_bots)} active bots...")

            for bot in running_bots:
                try:
                    # A. Reconnect Exchange
                    # Assuming Binance for now (Store exchange_id in DB later?)
                    exchange = ExchangeFactory.create_exchange(
                        "binance",
                        decrypt_value(bot.api_key),
                        decrypt_value(bot.secret_key),
                    )

                    # B. Start Loop (Managers are created inside loop pre-check or below?)
                    # Bot loop creates its own managers inside, BUT it needs `exchange_api` passed.
                    # It DOES NOT need managers passed (refactored earlier).
                    # Wait, look at `bot_loop` signature: `async def bot_loop(bot_id: int, exchange_api):`
                    # Yes, it instantiates managers internally. Perfect.

                    task = asyncio.create_task(bot_loop(bot.id, exchange))
                    active_bots[bot.id] = {"task": task, "exchange": exchange}
                    logger.info(f"Resumed Bot {bot.id}")

                except Exception as e:
                    logger.error(f"Failed to resume Bot {bot.id}: {e}")
                    # Update status to STOPPED?
                    await repo.update_status(bot.id, "STOPPED")

    yield
    # Cleanup active bots
    for b_id, bot_data in active_bots.items():
        bot_data["task"].cancel()
        if bot_data.get("exchange"):
            await bot_data["exchange"].close()
    logger.info("System Shutdown.")


app = FastAPI(lifespan=lifespan)

# --- Routes ---


@app.post("/start_bot")
async def start_bot(config: BotCreate, background_tasks: BackgroundTasks):
    # Use context manager for session
    async with db.get_session() as session:
        repo = BotRepository(session)

        # 1. Create Exchange Instance
        try:
            exchange = ExchangeFactory.create_exchange(
                "binance", config.api_key, config.secret_key
            )
            # Verify connection (Async)
            await exchange.get_ticker(config.pair)
        except Exception as e:
            # Ensure we close exchange if we fail here?
            # Exchange is created, but not attached to bot yet.
            await exchange.close()
            raise HTTPException(
                status_code=400, detail=f"Exchange connection failed: {e}"
            )

        # 2. Create Bot in DB
        grid_config = {
            "lower_limit": config.lower_limit,
            "upper_limit": config.upper_limit,
            "grid_count": config.grid_count,
            "amount_per_grid": config.amount / config.grid_count,
            "risk_level": config.risk_level,
            "mode": config.mode,
            "api_key": config.api_key,
            "secret_key": config.secret_key,
        }
        bot = await repo.create_bot(config.user_id, config.pair, grid_config)
        await repo.update_status(bot.id, "RUNNING")

        # 3. Setup Managers for Initial Placement
        order_repo = OrderRepository(session)
        trade_repo = TradeRepository(session)
        order_manager = OrderManager(exchange, order_repo, trade_repo)
        grid_strategy = GridStrategy(order_manager, repo)

        # 4. Initial Placement (Async)
        # We need current price first
        ticker = await exchange.get_ticker(config.pair)
        # Pass 'bot' (attached to session)
        await grid_strategy.place_initial_grid(bot, ticker["price"])

        # 'bot' ID is safe to pass.

    # 5. Start Loop
    # Note: loop creates its own sessions.
    task = asyncio.create_task(bot_loop(bot.id, exchange))
    active_bots[bot.id] = {"task": task, "exchange": exchange}

    return {"status": "started", "bot_id": bot.id}


@app.post("/stop_bot")
async def stop_bot(data: BotID):
    bot_id = data.bot_id
    if bot_id in active_bots:
        active_bots[bot_id]["task"].cancel()
        await active_bots[bot_id]["exchange"].close()

        async with db.get_session() as session:
            await BotRepository(session).update_status(bot_id, "STOPPED")

        del active_bots[bot_id]
        return {"status": "stopped"}

    return {"status": "not_running"}


@app.get("/health_stats")
def get_health():
    return health_system.get_stats()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
