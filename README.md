# Fydblock Spot Grid Trading Bot 

## Setup & Installation

1.  **Prerequisites**: Python 3.10+
2.  **Navigate to Directory**:
    ```bash
    cd python_grid_engine
    ```
3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

## Running the Application

Start the FastAPI server:
```bash
uvicorn main:app --reload
```
The API will be available at `http://localhost:8000`.
Docs: `http://localhost:8000/docs`

## Usage Guide

### 1. Start a Bot
```bash
curl -X POST "http://localhost:8000/start_bot" \
     -H "Content-Type: application/json" \
     -d '{
           "user_id": "user_123",
           "pair": "BTC/USDT",
           "amount": 1000,
           "lower_limit": 50000,
           "upper_limit": 60000,
           "grid_count": 10,
           "mode": "AUTO",
           "api_key": "YOUR_KEY",
           "secret_key": "YOUR_SECRET"
         }'
```

### 2. Check Health
```bash
curl "http://localhost:8000/health_stats"
```

### 3. Stop a Bot
```bash
curl -X POST "http://localhost:8000/stop_bot" \
     -d '{"bot_id": 1}'
```

## Backtesting

To run a backtest:
1.  Add CSV data to `backtest/data.csv`.
2.  Run a script (create `run_backtest.py` if needed or use interactive):
    ```python
    from backtest.historical_data import HistoricalDataLoader
    from backtest.backtester import BacktestEngine
    
    loader = HistoricalDataLoader()
    df = loader.load_dummy_data() # Or load_from_csv
    engine = BacktestEngine(initial_balance=1000)
    engine.setup_grid(50000, 45000, 55000, 10, 100)
    report = engine.run(df)
    print(report)
    ```

## Key Features Implemented

*   **Resilience**: SQLite WAL mode, Order State Persistence.
*   **Safety**: Strict ClientOrderID checks (Prefix [bot_](file:///g:/Fydblock/fydblock-grid%20latest/python_grid_engine/main.py#46-72)), Investment Isolation.
*   **Auto-Tuner**:
    *   **Reset Up**: Immediate reset when breaking upper limit.
    *   **Expand Down**: Expands lower limit when breaking lower limit (after 30m cooldown).
*   **Backtesting**: Simulation engine included.
