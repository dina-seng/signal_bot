# Trade Monorepo

Welcome to the Trade project repository.

## 📂 Repository Structure

- **[`server/`](./server)**: The core backend service built with Python and FastAPI for market analysis, Smart Money Concepts (SMC), indicators, backtesting, paper trading, and Telegram signal dispatching.
  - Detailed documentation: [Server README](./server/README.md)
  - Project architecture: [Server Project Structure](./server/PROJECT_STRUCTURE.md)
  - Deployment instructions: [Server Deployment Guide](./server/DEPLOYMENT_GUIDE.md)

## 🚀 Getting Started with the Backend Service

1. Navigate to the server folder:
   ```bash
   cd server
   ```

2. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Linux/macOS
   .venv\Scripts\activate     # On Windows
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run database setup / start the API:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

5. Run test suite:
   ```bash
   python -m pytest tests/
   ```
