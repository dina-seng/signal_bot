# Trade Monorepo

Welcome to the Trade project repository.

## 📂 Repository Structure

- **[`server/`](./server)**: The core backend service built with Python and FastAPI for market analysis, Smart Money Concepts (SMC), indicators, backtesting, paper trading, and Telegram signal dispatching.
  - Detailed documentation: [Server README](./server/README.md)
  - Project architecture: [Server Project Structure](./server/PROJECT_STRUCTURE.md)
  - Deployment instructions: [Server Deployment Guide](./server/DEPLOYMENT_GUIDE.md)
- **[`client/`](./client)**: "QuantView" Algorithmic Trading Dashboard built with React, TypeScript, Tailwind CSS, Recharts, and Lucide React.
  - High-performance Bloomberg terminal dark theme (#0a0a0f / #12121a)
  - Real-time 10s polling, Signal Matrix with per-pair alert toggles, Telegram alert configuration, active positions, interactive charts, and economic calendar risk monitor.

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

## 💻 Getting Started with the Client (QuantView)

1. Navigate to the client folder:
   ```bash
   cd client
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm run dev
   ```

4. Build for production:
   ```bash
   npm run build
   ```

