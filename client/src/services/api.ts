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

export interface AppConfig {
  min_confluence_score: number;
  duplicate_cooldown_hours: number;
  risk_per_order_pct: number;
  news_buffer_pre_min: number;
  news_buffer_post_min: number;
  min_rr_tp1: number;
  min_rr_tp2: number;
  quote_poll_seconds: number;
  mode: string;
  provider_name: string;
  quote_max_age_seconds: number;
  active_symbols: string[];
}

export interface BackendQuote {
  symbol: string;
  price: number;
  bid?: number | null;
  ask?: number | null;
  high?: number | null;
  low?: number | null;
  volume?: number | null;
  timestamp: string;
  source: string;
  provider?: string;
  provider_symbol?: string;
  age_seconds?: number;
  is_stale?: boolean;
  degraded?: boolean;
  fallback_reason?: string | null;
  cached?: boolean;
  cache_age_ms?: number | null;
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
  trend_alignment?: string | null;
  htf_trend?: string | null;
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

export interface BackendPaperTrade {
  id: number;
  account_id: number;
  signal_id?: number | null;
  symbol: string;
  direction: 'BUY' | 'SELL';
  order_type: string;
  status: string;
  target_entry_price?: number | null;
  entry_price: number;
  current_price: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2?: number | null;
  initial_position_size: number;
  remaining_position_size: number;
  margin_used: number;
  tp1_hit: boolean;
  realized_pnl: number;
  unrealized_pnl: number;
  pnl_pips: number;
  return_r: number;
  exit_price?: number | null;
  exit_reason?: string | null;
  opened_at: string;
  closed_at?: string | null;
  created_at: string;
}

export interface BackendFairValueGap {
  index: number;
  timestamp: string;
  fvg_type: 'BULLISH_FVG' | 'BEARISH_FVG';
  top_price: number;
  bottom_price: number;
  gap_size: number;
  gap_pips: number;
  is_mitigated: boolean;
  mitigated_timestamp?: string | null;
}

export interface BackendIndicatorAnalysis {
  symbol: string;
  timeframe: string;
  timestamp: string;
  current_price: number;
  ema: {
    ema_fast?: number | null;
    ema_mid?: number | null;
    ema_slow?: number | null;
    ema_trend: string;
    golden_cross: boolean;
    death_cross: boolean;
    price_vs_ema200?: string | null;
  };
  rsi: {
    rsi_value?: number | null;
    condition: string;
    is_overbought: boolean;
    is_oversold: boolean;
  };
  atr: {
    atr_value?: number | null;
    atr_pips?: number | null;
    volatility_state: string;
    suggested_sl_distance_pips?: number | null;
    suggested_tp_distance_pips?: number | null;
  };
  divergences?: Array<{
    divergence_type: string;
    start_timestamp: string;
    end_timestamp: string;
    price_start: number;
    price_end: number;
    rsi_start: number;
    rsi_end: number;
    strength: number;
  }>;
  recent_patterns?: Array<{
    index: number;
    timestamp: string;
    pattern_type: string;
    confidence: number;
    description: string;
  }>;
  active_fvgs: BackendFairValueGap[];
  confluence_bias: string;
  confluence_score: number;
}

export interface BackendLiquidityZones {
  symbol: string;
  timeframe: string;
  sr_zones: Array<{
    zone_type: 'SUPPORT' | 'RESISTANCE';
    price_low: number;
    price_high: number;
    center_price: number;
    touch_count: number;
    strength: number;
    is_fresh: boolean;
    last_touch_timestamp?: string | null;
  }>;
  liquidity_pools: Array<{
    pool_type: 'EQUAL_HIGHS' | 'EQUAL_LOWS';
    price_level: number;
    touch_points: number;
    first_timestamp: string;
    last_timestamp: string;
    is_swept: boolean;
  }>;
}

export interface BackendStructureAnalysis {
  symbol: string;
  timeframe: string;
  trend: string;
  trend_strength: number;
  key_resistance?: number | null;
  key_support?: number | null;
  last_swing_high?: any;
  last_swing_low?: any;
  higher_highs_count?: number;
  higher_lows_count?: number;
  lower_highs_count?: number;
  lower_lows_count?: number;
  equal_highs_count?: number;
  equal_lows_count?: number;
}

export interface BackendScannerStatus {
  is_enabled: boolean;
  interval_minutes: number;
  scanned_symbols: string[];
  scanned_timeframes: string[];
  auto_paper_trade: boolean;
  is_running: boolean;
  last_scan_at?: string | null;
  next_scan_at?: string | null;
  last_scan_signals_count: number;
  total_scans_completed: number;
}

export interface BackendMarketScanResult {
  scan_time: string;
  timeframe: string;
  symbols_scanned: number;
  qualified_signals_count: number;
  signals: Array<{
    symbol: string;
    timeframe: string;
    direction: string;
    setup_score: number;
    is_actionable: boolean;
    signal?: BackendSignal | null;
    blackout_blocked: boolean;
    reasons: string[];
  }>;
}

export interface BackendMarketSymbolInfo {
  symbol: string;
  base_currency: string;
  quote_currency: string;
  pip_size: number;
  description: string;
}

export interface BackendNewsSyncReport {
  timestamp: string;
  events_ingested: number;
  events_updated: number;
  total_events_in_db: number;
  source: string;
}

export interface TelegramBroadcastResponse {
  success: boolean;
  message_id?: number | null;
  chat_id?: string | null;
  text_sent: string;
  sent_at: string;
  error?: string | null;
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
  // 0. Configuration check (read-only, single source of truth)
  async getConfig(): Promise<{ data: AppConfig; durationMs: number }> {
    console.log('[API] GET /api/v1/config');
    return fetchWithTiming<AppConfig>(`${API_BASE}/config`);
  },

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
        close_ratio: 1.0,
        exit_reason: 'MANUAL_CLOSE_DASHBOARD',
      }),
    });
  },

  // 5. Portfolio Performance Metrics
  async getPerformance(): Promise<{ data: BackendPerformance; durationMs: number }> {
    console.log('[API] GET /api/v1/paper/performance');
    return fetchWithTiming<BackendPerformance>(`${API_BASE}/paper/performance`);
  },

  // 6. Paper Trading Trade History (Closed Positions)
  async getTradeHistory(limit = 50): Promise<{ data: BackendPaperTrade[]; durationMs: number }> {
    console.log(`[API] GET /api/v1/paper/trades?limit=${limit}`);
    return fetchWithTiming<BackendPaperTrade[]>(`${API_BASE}/paper/trades?limit=${limit}`);
  },

  // 7. Auto-Execute Paper Trade directly from Signal
  async tradeFromSignal(payload: {
    signal_id?: number | null;
    symbol: string;
    timeframe?: string;
    risk_percent?: number;
  }): Promise<{ data: BackendPaperTrade; durationMs: number }> {
    console.log('[API] POST /api/v1/paper/orders/from-signal', payload);
    return fetchWithTiming<BackendPaperTrade>(`${API_BASE}/paper/orders/from-signal`, {
      method: 'POST',
      body: JSON.stringify({
        signal_id: payload.signal_id ?? null,
        symbol: payload.symbol,
        timeframe: payload.timeframe || '1h',
        risk_percent: payload.risk_percent ?? 0.5,
      }),
    });
  },

  // 8. Signals (Default unified=true for multi-timeframe consensus)
  async getSignals(limit = 20, unified = true): Promise<{ data: BackendSignal[]; durationMs: number }> {
    console.log(`[API] GET /api/v1/signals?limit=${limit}&unified=${unified}`);
    return fetchWithTiming<BackendSignal[]>(`${API_BASE}/signals?limit=${limit}&unified=${unified}`);
  },

  // 9. Scan All Markets On-Demand (Unified Multi-Timeframe)
  async scanMarkets(timeframe = '1h', unified = true): Promise<{ data: BackendMarketScanResult; durationMs: number }> {
    console.log(`[API] GET /api/v1/signals/scan?unified=${unified}&timeframe=${timeframe}`);
    return fetchWithTiming<BackendMarketScanResult>(`${API_BASE}/signals/scan?unified=${unified}&timeframe=${timeframe}&persist_qualified=true`);
  },

  // 10. Technical Indicators (EMA 20/50/200, RSI, ATR, FVGs, Divergences, Patterns)
  async getIndicators(symbol: string, timeframe = '15m', limit = 200): Promise<{ data: BackendIndicatorAnalysis; durationMs: number }> {
    const encodedSym = encodeURIComponent(symbol);
    console.log(`[API] GET /api/v1/indicators/${encodedSym}?timeframe=${timeframe}`);
    return fetchWithTiming<BackendIndicatorAnalysis>(`${API_BASE}/indicators/${encodedSym}?timeframe=${timeframe}&limit=${limit}`);
  },

  // 11. Liquidity, Support/Resistance Zones & Equal High/Low Pools
  async getLiquidityZones(symbol: string, timeframe = '15m', limit = 200): Promise<{ data: BackendLiquidityZones; durationMs: number }> {
    const encodedSym = encodeURIComponent(symbol);
    console.log(`[API] GET /api/v1/liquidity/${encodedSym}/zones?timeframe=${timeframe}`);
    return fetchWithTiming<BackendLiquidityZones>(`${API_BASE}/liquidity/${encodedSym}/zones?timeframe=${timeframe}&limit=${limit}`);
  },

  // 12. Market Structure Analysis (HH, HL, LH, LL, Swings)
  async getStructure(symbol: string, timeframe = '15m', limit = 200): Promise<{ data: BackendStructureAnalysis; durationMs: number }> {
    const encodedSym = encodeURIComponent(symbol);
    console.log(`[API] GET /api/v1/structure/${encodedSym}?timeframe=${timeframe}`);
    return fetchWithTiming<BackendStructureAnalysis>(`${API_BASE}/structure/${encodedSym}?timeframe=${timeframe}&limit=${limit}`);
  },

  // 13. News Calendar
  async getNewsCalendar(limit = 25): Promise<{ data: BackendNewsEvent[]; durationMs: number }> {
    console.log(`[API] GET /api/v1/news/calendar?limit=${limit}`);
    return fetchWithTiming<BackendNewsEvent[]>(`${API_BASE}/news/calendar?limit=${limit}`);
  },

  // 14. Sync Economic News Calendar from Provider
  async syncNewsCalendar(): Promise<{ data: BackendNewsSyncReport; durationMs: number }> {
    console.log('[API] POST /api/v1/news/sync');
    return fetchWithTiming<BackendNewsSyncReport>(`${API_BASE}/news/sync`, { method: 'POST' });
  },

  // 15. News Blackout Check
  async checkBlackout(symbol: string): Promise<{ data: BackendBlackoutCheck; durationMs: number }> {
    const encodedSym = encodeURIComponent(symbol);
    console.log(`[API] GET /api/v1/news/check/${encodedSym}`);
    return fetchWithTiming<BackendBlackoutCheck>(`${API_BASE}/news/check/${encodedSym}`);
  },

  // 16. Historical Candlesticks for Charts & Pricing
  async getCandles(symbol: string, timeframe = '15m', limit = 30): Promise<{ data: BackendCandle[]; durationMs: number }> {
    const encodedSym = encodeURIComponent(symbol);
    console.log(`[API] GET /api/v1/market/${encodedSym}/candles?timeframe=${timeframe}&limit=${limit}`);
    return fetchWithTiming<BackendCandle[]>(`${API_BASE}/market/${encodedSym}/candles?timeframe=${timeframe}&limit=${limit}`);
  },

  // 17. Real-Time Price Quote from Provider
  async getQuote(symbol = 'XAU/USD'): Promise<{ data: BackendQuote; durationMs: number }> {
    const encodedSym = encodeURIComponent(symbol);
    console.log(`[API] GET /api/v1/market/${encodedSym}/quote`);
    return fetchWithTiming<BackendQuote>(`${API_BASE}/market/${encodedSym}/quote`);
  },

  // 18. Fetch latest market prices for active pairs (Real-time quote with candle fallback)
  async getLatestPrices(): Promise<Record<string, number>> {
    try {
      const quoteRes = await this.getQuote('XAU/USD');
      if (quoteRes.data && typeof quoteRes.data.price === 'number' && quoteRes.data.price > 0) {
        return { 'XAU/USD': quoteRes.data.price };
      }
    } catch {
      // Fallback to candle close if quote provider is offline or busy
    }

    const symbols = ['XAU/USD'];
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

  // 19. Supported Symbols Metadata
  async getSymbols(): Promise<{ data: BackendMarketSymbolInfo[]; durationMs: number }> {
    console.log('[API] GET /api/v1/market/symbols');
    return fetchWithTiming<BackendMarketSymbolInfo[]>(`${API_BASE}/market/symbols`);
  },

  // 20. Sync Market Data from Provider
  async syncMarketData(symbol?: string, timeframe?: string, limit = 100): Promise<{ data: any; durationMs: number }> {
    console.log('[API] POST /api/v1/market/sync');
    return fetchWithTiming<any>(`${API_BASE}/market/sync`, {
      method: 'POST',
      body: JSON.stringify({ symbol, timeframe, limit }),
    });
  },

  // 20. Telegram Bot Status
  async getTelegramStatus(): Promise<{ data: BackendTelegramStatus; durationMs: number }> {
    console.log('[API] GET /api/v1/telegram/status');
    return fetchWithTiming<BackendTelegramStatus>(`${API_BASE}/telegram/status`);
  },

  // 21. Send Telegram Test Alert / Broadcast
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

  // 22. Automated Scanner Status
  async getScannerStatus(): Promise<{ data: BackendScannerStatus; durationMs: number }> {
    console.log('[API] GET /api/v1/telegram/scanner/status');
    return fetchWithTiming<BackendScannerStatus>(`${API_BASE}/telegram/scanner/status`);
  },

  // 23. Manually Trigger Market Scanner Cycle
  async triggerScannerCycle(timeframe = '1h', broadcast = true, autoTrade = true): Promise<{ data: any; durationMs: number }> {
    console.log(`[API] POST /api/v1/telegram/scanner/trigger?timeframe=${timeframe}`);
    return fetchWithTiming<any>(
      `${API_BASE}/telegram/scanner/trigger?timeframe=${timeframe}&broadcast=${broadcast}&auto_trade=${autoTrade}`,
      { method: 'POST' }
    );
  },
};
