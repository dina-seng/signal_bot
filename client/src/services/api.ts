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
 * - /api/v1/market/{symbol}/candles
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
  signal_id?: number | null;
  symbol: string;
  direction: 'BUY' | 'SELL';
  order_type: string;
  status: string;
  entry_price: number;
  current_price: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2?: number | null;
  initial_position_size: number;
  remaining_position_size: number;
  margin_used: number;
  unrealized_pnl: number;
  pnl_pips: number;
  opened_at: string;
}

export interface BackendPerformance {
  initial_balance?: number;
  current_balance?: number;
  current_equity?: number;
  total_realized_pnl?: number;
  total_unrealized_pnl?: number;
  total_return_pct?: number;
  margin_used?: number;
  free_margin?: number;
  margin_level_pct?: number;
  total_trades?: number;
  open_trades?: number;
  closed_trades?: number;
  winning_trades?: number;
  losing_trades?: number;
  win_rate?: number;
  win_rate_pct?: number;
  profit_factor?: number;
  max_drawdown?: number;
  max_drawdown_pct?: number;
  sharpe_ratio?: number;
  expectancy_pips?: number;
}

export interface BackendSignal {
  id: number;
  symbol: string;
  timeframe: string;
  direction: 'BUY' | 'SELL';
  setup_score?: number;
  confluence_score?: number;
  entry_price: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2?: number;
  risk_reward?: number;
  risk_reward_ratio?: number;
  reasons?: string[];
  status: string;
  is_broadcasted?: boolean;
  timestamp: string;
}

export interface BackendNewsEvent {
  id: number;
  currency: string;
  event_name?: string;
  title?: string;
  event?: string;
  impact: 'HIGH' | 'MEDIUM' | 'LOW';
  scheduled_time: string;
  previous: string;
  forecast: string;
  actual?: string | null;
}

export interface BackendBlackoutCheck {
  in_blackout: boolean;
  symbol: string;
  reason?: string;
  event_title?: string;
  minutes_to_next_event?: number;
}

export interface BackendCandle {
  id: number;
  symbol: string;
  timeframe: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
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

// Fetch wrapper with timeout and response timing
async function fetchWithTiming<T>(url: string, options: RequestInit = {}, timeoutMs = 4000): Promise<{ data: T; durationMs: number }> {
  const start = performance.now();
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
    const durationMs = Math.round(performance.now() - start);

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }

    const data = await res.json();
    return { data, durationMs };
  } finally {
    clearTimeout(id);
  }
}

export const quantViewApi = {
  // 1. Health check
  async getHealth(): Promise<{ data: HealthResponse; durationMs: number }> {
    console.log('[API] GET /api/v1/health');
    return fetchWithTiming<HealthResponse>(`${API_BASE}/health`);
  },

  // 2. Paper Trading Account
  async getAccount(): Promise<{ data: BackendAccount; durationMs: number }> {
    console.log('[API] GET /api/v1/paper/account');
    return fetchWithTiming<BackendAccount>(`${API_BASE}/paper/account`);
  },

  // 3. Paper Trading Open Positions
  async getPositions(): Promise<{ data: BackendPosition[]; durationMs: number }> {
    console.log('[API] GET /api/v1/paper/positions?status=OPEN');
    return fetchWithTiming<BackendPosition[]>(`${API_BASE}/paper/positions?status=OPEN`);
  },

  // 4. Close Position
  async closePosition(tradeId: number | string): Promise<{ data: BackendPosition; durationMs: number }> {
    console.log(`[API] POST /api/v1/paper/positions/${tradeId}/close`);
    return fetchWithTiming<BackendPosition>(`${API_BASE}/paper/positions/${tradeId}/close`, {
      method: 'POST',
      body: JSON.stringify({
        close_fraction: 1.0,
        exit_reason: 'MANUAL_CLOSE_DASHBOARD',
      }),
    });
  },

  // 5. Portfolio Performance Metrics
  async getPerformance(): Promise<{ data: BackendPerformance; durationMs: number }> {
    console.log('[API] GET /api/v1/paper/performance');
    return fetchWithTiming<BackendPerformance>(`${API_BASE}/paper/performance`);
  },

  // 6. Signals
  async getSignals(limit = 20): Promise<{ data: BackendSignal[]; durationMs: number }> {
    console.log(`[API] GET /api/v1/signals?limit=${limit}`);
    return fetchWithTiming<BackendSignal[]>(`${API_BASE}/signals?limit=${limit}`);
  },

  // 7. News Calendar
  async getNewsCalendar(limit = 25): Promise<{ data: BackendNewsEvent[]; durationMs: number }> {
    console.log(`[API] GET /api/v1/news/calendar?limit=${limit}`);
    return fetchWithTiming<BackendNewsEvent[]>(`${API_BASE}/news/calendar?limit=${limit}`);
  },

  // 8. News Blackout Check
  async checkBlackout(symbol: string): Promise<{ data: BackendBlackoutCheck; durationMs: number }> {
    console.log(`[API] GET /api/v1/news/check/${symbol}`);
    return fetchWithTiming<BackendBlackoutCheck>(`${API_BASE}/news/check/${symbol}`);
  },

  // 9. Historical Candlesticks for Charts & Pricing
  async getCandles(symbol: string, timeframe = '15m', limit = 25): Promise<{ data: BackendCandle[]; durationMs: number }> {
    console.log(`[API] GET /api/v1/market/${symbol}/candles?timeframe=${timeframe}&limit=${limit}`);
    return fetchWithTiming<BackendCandle[]>(`${API_BASE}/market/${symbol}/candles?timeframe=${timeframe}&limit=${limit}`);
  },

  // 10. Fetch latest market prices for all pairs
  async getLatestPrices(): Promise<Record<string, number>> {
    const symbols = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'XAU/USD'];
    const prices: Record<string, number> = {};

    await Promise.allSettled(
      symbols.map(async (sym) => {
        try {
          const res = await this.getCandles(sym, '15m', 1);
          if (res.data && res.data.length > 0) {
            prices[sym] = res.data[res.data.length - 1].close;
          }
        } catch {
          // Keep empty if failed
        }
      })
    );

    return prices;
  },

  // 11. Telegram Bot Status
  async getTelegramStatus(): Promise<{ data: BackendTelegramStatus; durationMs: number }> {
    console.log('[API] GET /api/v1/telegram/status');
    return fetchWithTiming<BackendTelegramStatus>(`${API_BASE}/telegram/status`);
  },

  // 12. Send Telegram Test Alert / Broadcast
  async sendTelegramBroadcast(text: string): Promise<{ data: TelegramBroadcastResponse; durationMs: number }> {
    console.log('[API] POST /api/v1/telegram/broadcast');
    return fetchWithTiming<TelegramBroadcastResponse>(`${API_BASE}/telegram/broadcast`, {
      method: 'POST',
      body: JSON.stringify({
        text,
        parse_mode: 'Markdown',
      }),
    });
  },
};
