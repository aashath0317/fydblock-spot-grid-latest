from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Literal
import uvicorn
import asyncio
from contextlib import asynccontextmanager

# Internal modules
from database.db_manager import db
from database.repositories import BotRepository, OrderRepository, TradeRepository
from execution.order_manager import OrderManager
from execution.balance_manager import BalanceManager
from exchange.factory import ExchangeFactory
from strategies.auto_tuner import AutoTuner
from utils.logger import setup_logger
from utils.health import health_system

logger = setup_logger("main_api")


# --- Schemas ---
class BotCreate(BaseModel):
    user_id: str
    pair: str
    amount: float
    lower_limit: float
    upper_limit: float
    grid_count: int
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


async def bot_loop(
    bot_id: int, exchange_api, order_manager: OrderManager, auto_tuner: AutoTuner
):
    """
    Real-time WebSocket Loop.
    """
    logger.info(f"Bot {bot_id}: Async WS Loop started.")
    try:
        # Initial boot check
        await order_manager.sync_orders(bot_id)

        while True:
            # A. Watch for Price Update (Real-time Blocking until update)
            # This replaces "sleep"
            try:
                # Assuming all bots watch the same pair in this loop context?
                # Ideally, we pass the pair.
                bot = BotRepository(db.get_session()).get_bot(
                    bot_id
                )  # Optimization: Cache pair
                if not bot:
                    break

                ticker = await exchange_api.watch_ticker(bot.pair)
                current_price = ticker["price"]

                # B. Health Heartbeat
                health_system.heartbeat()

                # C. Checks
                # 1. Sync Orders (Maybe not on EVERY tick? Or rely on WS for orders too?)
                # For basic implementation, we can sync less frequently or on signal.
                # Let's sync every tick for safety if latency permits, OR usage of watch_orders (ToDo)
                # But to avoid API blocking, let's trust WS price but sync orders occasionally or on price cross?
                # Optimization: Async sync
                await order_manager.sync_orders(bot_id)

                # 2. Auto Tune Check
                # action = auto_tuner.check_adjustment(bot, current_price)
                # if action != NONE: await execute_adjustment...

                # 3. Grid Logic (Check if grid crossed) -> Place/Cancel
                # TODO: Implement Grid Logic here

            except Exception as e:
                logger.error(f"Bot {bot_id} Loop Error: {e}")
                health_system.log_error()
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
    db.init_db()
    logger.info("System Startup: DB Initialized.")
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
    session = db.get_session()
    repo = BotRepository(session)

    # 1. Create Exchange Instance
    try:
        exchange = ExchangeFactory.create_exchange(
            "binance", config.api_key, config.secret_key
        )
        # Verify connection (Async)
        await exchange.get_ticker(config.pair)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Exchange connection failed: {e}")

    # 2. Create Bot in DB
    grid_config = {
        "lower_limit": config.lower_limit,
        "upper_limit": config.upper_limit,
        "grid_count": config.grid_count,
        "amount_per_grid": config.amount / config.grid_count,
        "risk_level": config.risk_level,
        "mode": config.mode,
    }
    bot = repo.create_bot(config.user_id, config.pair, grid_config)
    repo.update_status(bot.id, "RUNNING")

    # 3. Setup Managers
    order_repo = OrderRepository(session)
    trade_repo = TradeRepository(session)
    order_manager = OrderManager(exchange, order_repo, trade_repo)
    auto_tuner = AutoTuner()

    # 4. Start Loop
    task = asyncio.create_task(bot_loop(bot.id, exchange, order_manager, auto_tuner))
    active_bots[bot.id] = {"task": task, "exchange": exchange}

    return {"status": "started", "bot_id": bot.id}


@app.post("/stop_bot")
async def stop_bot(data: BotID):
    bot_id = data.bot_id
    if bot_id in active_bots:
        active_bots[bot_id]["task"].cancel()
        await active_bots[bot_id]["exchange"].close()

        session = db.get_session()
        BotRepository(session).update_status(bot_id, "STOPPED")

        del active_bots[bot_id]
        return {"status": "stopped"}

    return {"status": "not_running"}


@app.get("/health_stats")
def get_health():
    return health_system.get_stats()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
