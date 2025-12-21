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
active_bots = {}  # bot_id -> {'tasks': [Task...], 'exchange': ExchangeInterface}


async def orders_loop(bot_id: int, exchange_api):
    """
    WebSocket Loop for Order Updates (Pure WS).
    """
    logger.info(f"Bot {bot_id}: Orders WS Loop started.")

    order_manager = OrderManager(exchange_api)
    grid_strategy = GridStrategy(order_manager)

    while True:
        try:
            # 1. Get Pair (Need DB or assume passed? Fetch once.)
            async with db.get_session() as session:
                bot = await BotRepository(session).get_bot(bot_id)
            if not bot:
                break
            pair = bot.pair

            # 2. Watch Orders (Blocking)
            # This blocks until an order update arrives.
            try:
                updated_orders = await exchange_api.watch_orders(pair)
            except asyncio.TimeoutError:
                continue

            if not updated_orders:
                continue

            logger.info(f"Bot {bot_id}: Received {len(updated_orders)} order updates.")

            # 3. Process Logic (Stateful)
            async with db.get_session() as session:
                # Attach session
                order_manager.order_repo = OrderRepository(session)
                grid_strategy.bot_repo = BotRepository(session)

                # Re-fetch bot within session to avoid detachment
                bot = await BotRepository(session).get_bot(bot_id)

                # Filter for Fills
                filled_for_grid = []
                for o in updated_orders:
                    # Update matching DB order
                    if o.get("client_order_id"):
                        # We prefer updating by client_order_id
                        status = o["status"]
                        if status == "closed":
                            # Filled
                            await order_manager.order_repo.update_status(
                                o["client_order_id"], "FILLED", filled=o["filled"]
                            )
                            filled_for_grid.append(o)
                            logger.info(
                                f"Bot {bot_id}: Order {o['client_order_id']} FILLED."
                            )
                        elif status == "canceled":
                            await order_manager.order_repo.update_status(
                                o["client_order_id"], "CANCELED"
                            )
                        elif status == "open":
                            # New or partial?
                            # Update filled qty for partials
                            await order_manager.order_repo.update_status(
                                o["client_order_id"], "OPEN", filled=o["filled"]
                            )

                # Trigger Grid Update
                if filled_for_grid:
                    await grid_strategy.update_grid(bot, filled_for_grid)

        except Exception as e:
            logger.error(f"Bot {bot_id}: Orders Loop Error: {e}")
            await asyncio.sleep(5)

        finally:
            # Cleanup
            order_manager.order_repo = None
            grid_strategy.bot_repo = None


async def price_loop(bot_id: int, exchange_api):
    """
    WebSocket Loop for Price Updates (Health, StopLoss, AutoTuner).
    """
    logger.info(f"Bot {bot_id}: Price WS Loop started.")

    # Persistent Objects
    order_manager = OrderManager(exchange_api)
    grid_strategy = GridStrategy(order_manager)
    auto_tuner = AutoTuner()

    while True:
        try:
            # 1. Fetch Bot to get Pair & Config
            async with db.get_session() as session:
                bot = await BotRepository(session).get_bot(bot_id)

            if not bot:
                logger.warning(f"Bot {bot_id} not found/stopped. Exiting Price Loop.")
                break

            pair = bot.pair

            # A. Watch Price (Blocking)
            try:
                # 5s timeout allows us to check health/stop even if no trades occur
                ticker = await asyncio.wait_for(
                    exchange_api.watch_ticker(pair), timeout=5.0
                )
                current_price = ticker["price"]
            except asyncio.TimeoutError:
                health_system.heartbeat()
                continue

            # B. Health
            health_system.heartbeat()

            # C. Stop Loss Check
            if bot.stop_loss and current_price <= bot.stop_loss:
                logger.critical(
                    f"Bot {bot_id}: STOP LOSS HIT ({current_price} <= {bot.stop_loss})."
                )
                async with db.get_session() as sl_session:
                    # Inject session for cancellation
                    order_manager.order_repo = OrderRepository(sl_session)
                    await order_manager.cancel_bot_orders(bot_id)
                    await BotRepository(sl_session).update_status(bot_id, "STOPPED")
                break

            # D. Auto Tune Actions
            # We need a new session for logic
            async with db.get_session() as session:
                bot_repo = BotRepository(session)
                # Re-fetch attached bot
                bot = await bot_repo.get_bot(bot_id)
                if not bot:
                    break

                # Attach Repos
                order_manager.order_repo = OrderRepository(session)
                grid_strategy.bot_repo = bot_repo

                # Check Logic
                action = auto_tuner.check_adjustment(bot, current_price)
                if action != OptimizationAction.NONE:
                    logger.info(f"Bot {bot_id}: AutoTuner triggered {action.value}")

                    # Calculate New Params
                    new_params = auto_tuner.calculate_new_params(
                        bot, current_price, action
                    )

                    if new_params:
                        # Cancel All
                        logger.info(f"Bot {bot_id}: Cancelling orders for AutoTune...")
                        await order_manager.cancel_bot_orders(bot_id)

                        # Update Config
                        updated_bot = await bot_repo.update_grid_config(
                            bot_id, new_params
                        )

                        # Re-Place Grid
                        logger.info(f"Bot {bot_id}: Placing new grid...")
                        await grid_strategy.place_initial_grid(
                            updated_bot, current_price
                        )

                        # Update Trailing Timestamp
                        if action == OptimizationAction.EXPAND_DOWN:
                            updated_bot.last_trailing_update = (
                                datetime.datetime.utcnow()
                            )
                            await session.commit()

        except asyncio.CancelledError:
            logger.info(f"Bot {bot_id}: Price Loop cancelled.")
            await exchange_api.close()
            break

        except Exception as e:
            logger.critical(f"Bot {bot_id} Price Loop Error: {e}")
            health_system.log_error()
            await asyncio.sleep(5)

        finally:
            # Cleanup per iteration references (safety)
            order_manager.order_repo = None
            grid_strategy.bot_repo = None


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

                    task_price = asyncio.create_task(price_loop(bot.id, exchange))
                    task_orders = asyncio.create_task(orders_loop(bot.id, exchange))
                    active_bots[bot.id] = {
                        "tasks": [task_price, task_orders],
                        "exchange": exchange,
                    }
                    logger.info(f"Resumed Bot {bot.id}")

                except Exception as e:
                    logger.error(f"Failed to resume Bot {bot.id}: {e}")
                    # Update status to STOPPED?
                    await repo.update_status(bot.id, "STOPPED")

    yield
    # Cleanup active bots
    for b_id, bot_data in active_bots.items():
        for task in bot_data["tasks"]:
            task.cancel()
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
    task_price = asyncio.create_task(price_loop(bot.id, exchange))
    task_orders = asyncio.create_task(orders_loop(bot.id, exchange))
    active_bots[bot.id] = {"tasks": [task_price, task_orders], "exchange": exchange}

    return {"status": "started", "bot_id": bot.id}


@app.post("/stop_bot")
async def stop_bot(data: BotID):
    bot_id = data.bot_id
    if bot_id in active_bots:
        for task in active_bots[bot_id]["tasks"]:
            task.cancel()
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
