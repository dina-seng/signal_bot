/**
 * QuantView Backend API Service
 * Connects frontend dashboard to FastAPI backend endpoints:
 * - /api/v1/health
 * - /api/v1/paper/account
 * - /api/v1/paper/positions
 * - /api/v1/paper/positions/{id}/close
 * - /api/v1/paper/performance
 * - /api/v1/signals
 * - /api/v1/signals/scan
 * - /api/v1/news/calendar
 * - /api/v1/news/check/{symbol}
 * - /api/v1/telegram/status
 * - /api/v1/telegram/broadcast
 */

const API_BASE = import.meta.env.VITE_API_URL || '/api/v1';

export interface HealthResponse {
  status: string;
  database_connected: boolean;
  app_version: string;
  supported_symbols: string[];
  supported_timeframes: string[];
  candle_counts: Record<string, Record<string, number>>;
  server_time_utc: string;
  scanner_enabled: boolean;
  scanner_running: boolean;
}

export interface BackendAccount {
  id: number;
  name: string;
  balance: number;
  equity: number;
  margin_used: number;
  free_margin: number;
  margin_level_pct: number;
  currency: string;
  open_positions_count: number;
  floating_pnl: number;
  realized_pnl: number;
  total_return_pct: number;
}

export interface BackendPosition {
  id: number;
  account_id: number;
  signal_id?: number;
  symbol: string;
  direction: 'BUY' | 'SELL';
  order_type: string;
  status: string;
  entry_price: number;
  current_price: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
  initial_position_size: number;
  remaining_position_size: number;
  margin_used: number;
  unrealized_pnl: number;
  pnl_pips: number;
  opened_at: string;
}

export interface BackendPerformance {
  account_id: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_pct: number;
  profit_factor: number;
  expectancy_pips: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
}

export interface BackendSignal {
  id: number;
  symbol: string;
  direction: 'BUY' | 'SELL' | 'WAIT';
  timeframe: string;
  entry_price: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
  risk_reward_ratio: number;
  composite_score: number;
  setup_quality: string;
  status: string;
  timestamp: string;
  reason?: string;
}

export interface BackendTelegramStatus {
  is_configured: boolean;
  bot_token_present: boolean;
  chat_id_present: boolean;
  mode: string;
  total_messages_sent: number;
  last_message_at?: string;
}

export interface TelegramBroadcastResponse {
  success: boolean;
  message_id?: number;
  chat_id?: string;
  text_sent: string;
  sent_at: string;
  error?: string;
}

// Helper fetch wrapper with timeout
async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = 4000): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });
    return res;
  } finally {
    clearTimeout(id);
  }
}

export const quantViewApi = {
  // 1. Health check
  async getHealth(): Promise<HealthResponse> {
    const res = await fetchWithTimeout(`${API_BASE}/health`);
    if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
    return res.json();
  },

  // 2. Paper Trading Account
  async getAccount(): Promise<BackendAccount> {
    const res = await fetchWithTimeout(`${API_BASE}/paper/account`);
    if (!res.ok) throw new Error(`Fetch account failed: ${res.statusText}`);
    return res.json();
  },

  // 3. Paper Trading Open Positions
  async getPositions(): Promise<BackendPosition[]> {
    const res = await fetchWithTimeout(`${API_BASE}/paper/positions?status=OPEN`);
    if (!res.ok) throw new Error(`Fetch positions failed: ${res.statusText}`);
    return res.json();
  },

  // 4. Close Position
  async closePosition(tradeId: number | string): Promise<BackendPosition> {
    const res = await fetchWithTimeout(`${API_BASE}/paper/positions/${tradeId}/close`, {
      method: 'POST',
      body: JSON.stringify({
        close_fraction: 1.0,
        exit_reason: 'MANUAL_CLOSE_DASHBOARD',
      }),
    });
    if (!res.ok) throw new Error(`Close position #${tradeId} failed: ${res.statusText}`);
    return res.json();
  },

  // 5. Portfolio Performance Metrics
  async getPerformance(): Promise<BackendPerformance> {
    const res = await fetchWithTimeout(`${API_BASE}/paper/performance`);
    if (!res.ok) throw new Error(`Fetch performance failed: ${res.statusText}`);
    return res.json();
  },

  // 6. Signals
  async getSignals(limit = 10): Promise<BackendSignal[]> {
    const res = await fetchWithTimeout(`${API_BASE}/signals?limit=${limit}`);
    if (!res.ok) throw new Error(`Fetch signals failed: ${res.statusText}`);
    return res.json();
  },

  // 7. News Calendar
  async getNewsCalendar(limit = 15): Promise<any[]> {
    const res = await fetchWithTimeout(`${API_BASE}/news/calendar?limit=${limit}`);
    if (!res.ok) throw new Error(`Fetch news calendar failed: ${res.statusText}`);
    return res.json();
  },

  // 8. News Blackout Check
  async checkBlackout(symbol: string): Promise<any> {
    const cleanSym = encodeURIComponent(symbol);
    const res = await fetchWithTimeout(`${API_BASE}/news/check/${cleanSym}`);
    if (!res.ok) throw new Error(`Blackout check failed for ${symbol}`);
    return res.json();
  },

  // 9. Telegram Bot Status
  async getTelegramStatus(): Promise<BackendTelegramStatus> {
    const res = await fetchWithTimeout(`${API_BASE}/telegram/status`);
    if (!res.ok) throw new Error(`Fetch Telegram status failed: ${res.statusText}`);
    return res.json();
  },

  // 10. Send Telegram Test Alert / Broadcast
  async sendTelegramBroadcast(text: string): Promise<TelegramBroadcastResponse> {
    const res = await fetchWithTimeout(`${API_BASE}/telegram/broadcast`, {
      method: 'POST',
      body: JSON.stringify({
        text,
        parse_mode: 'Markdown',
      }),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Telegram broadcast failed with status ${res.status}`);
    }
    return res.json();
  },

  // 11. Trigger Scanner
  async triggerScannerCycle(): Promise<any> {
    const res = await fetchWithTimeout(`${API_BASE}/telegram/scanner/trigger?timeframe=1h&broadcast=true&auto_trade=true`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`Scanner trigger failed: ${res.statusText}`);
    return res.json();
  },
};
