import {
  PerformanceStats,
  EquityDataPoint,
  TradeSignal,
  Position,
  NewsEvent,
  RiskStatus,
  AlertConfiguration,
  AccountSummary,
  PairSymbol,
} from '../types';

export const initialAccountSummary: AccountSummary = {
  balance: 100,
  equity: 100,
  unrealizedPnl: 23.52,
  unrealizedPnlPercent: 0.29,
  marginUsed: 155.39,
  marginAvailable: 7916.13,
  marginLevelPercent: 5194.36,
  activePositionsCount: 2,
  todayPnl: 23.52,
  brokerStatus: 'CONNECTED',
  latencyMs: 14,
};

export const initialPerformanceStats: PerformanceStats = {
  winRate: 68.4,
  winRateDelta: 1.8,
  profitFactor: 2.15,
  profitFactorDelta: 0.12,
  totalTrades: 4,
  totalTradesDelta: 2,
  maxDrawdown: 3.4,
  maxDrawdownDelta: -0.2,
  sharpeRatio: 1.94,
  expectancyPips: 16.5,
};

export const equityHistoryData: Record<'1W' | '1M' | '3M' | 'ALL', EquityDataPoint[]> = {
  '1W': [
    { timestamp: 'Mon 00:00', equity: 7850, balance: 7800, drawdown: 0.4 },
    { timestamp: 'Tue 00:00', equity: 7920, balance: 7800, drawdown: 0.2 },
    { timestamp: 'Wed 00:00', equity: 8010, balance: 7950, drawdown: 0.1 },
    { timestamp: 'Thu 00:00', equity: 8040, balance: 8000, drawdown: 0.3 },
    { timestamp: 'Fri 00:00', equity: 8055, balance: 8048, drawdown: 0.1 },
    { timestamp: 'Today', equity: 8071.52, balance: 8048, drawdown: 0.0 },
  ],
  '1M': [
    { timestamp: 'Week 1', equity: 7400, balance: 7350, drawdown: 1.2 },
    { timestamp: 'Week 2', equity: 7650, balance: 7600, drawdown: 0.8 },
    { timestamp: 'Week 3', equity: 7880, balance: 7800, drawdown: 0.5 },
    { timestamp: 'Week 4', equity: 8020, balance: 8000, drawdown: 0.4 },
    { timestamp: 'Current', equity: 8071.52, balance: 8048, drawdown: 0.0 },
  ],
  '3M': [
    { timestamp: 'Jul W1', equity: 6800, balance: 6750, drawdown: 2.1 },
    { timestamp: 'Jul W3', equity: 7100, balance: 7000, drawdown: 1.5 },
    { timestamp: 'Aug W1', equity: 7450, balance: 7400, drawdown: 1.1 },
    { timestamp: 'Aug W3', equity: 7750, balance: 7700, drawdown: 0.8 },
    { timestamp: 'Sep W1', equity: 8010, balance: 8000, drawdown: 0.4 },
    { timestamp: 'Current', equity: 8071.52, balance: 8048, drawdown: 0.0 },
  ],
  'ALL': [
    { timestamp: 'Jan', equity: 6000, balance: 6000, drawdown: 0.0 },
    { timestamp: 'Mar', equity: 6600, balance: 6500, drawdown: 1.5 },
    { timestamp: 'May', equity: 7200, balance: 7100, drawdown: 2.1 },
    { timestamp: 'Jul', equity: 7650, balance: 7600, drawdown: 1.2 },
    { timestamp: 'Sep', equity: 8071.52, balance: 8048, drawdown: 0.0 },
  ],
};

export const initialSignals: TradeSignal[] = [
  {
    id: 'SIG-XAUUSD-03',
    symbol: 'XAU/USD',
    direction: 'BUY',
    confluenceScore: 92,
    timeframe: '15m / 1h',
    entryPrice: 4411.60,
    stopLoss: 4398.00,
    takeProfit1: 4438.80,
    takeProfit2: 4465.00,
    riskRewardRatio: '1:2.0',
    pipsAtRisk: 136.0,
    timestamp: '8m ago',
    setupReason: 'Gold Trend Continuation + 15m Fair Value Gap Mitigation + DXY Weakness',
    notifyEnabled: true,
    status: 'ACTIVE',
    hasActiveSignal: true,
    aiConfidence: 94,
    aiReasoning: 'Order-flow imbalance detected on XAU/USD. Clean liquidity sweep beneath local support followed by institutional displacement into Bullish FVG with heavy spot bid volume.',
  },
  {
    id: 'SIG-US100-01',
    symbol: 'US100',
    direction: 'SELL',
    confluenceScore: 84,
    timeframe: '15m',
    entryPrice: 20450.50,
    stopLoss: 20520.00,
    takeProfit1: 20310.00,
    takeProfit2: 20180.00,
    riskRewardRatio: '1:2.0',
    pipsAtRisk: 69.5,
    timestamp: 'Just now',
    setupReason: 'Confirmed Bearish BOS + Buy-Side Liquidity Sweep into 15m Premium FVG',
    notifyEnabled: true,
    status: 'ACTIVE',
    hasActiveSignal: true,
    aiConfidence: 89,
    aiReasoning: 'Institutional supply zone test on US100 following aggressive opening drive. Sweep of Asian session highs followed by strong displacement down. Bearish fair value gap mitigated with delta divergence.',
  },
];

export const initialPositions: Position[] = [
  {
    id: '4',
    symbol: 'XAU/USD',
    side: 'BUY',
    size: 0.1,
    entryPrice: 4410.50,
    currentPrice: 4412.80,
    stopLoss: 4398.00,
    takeProfit: 4438.00,
    pnl: 23.00,
    pnlPercent: 0.28,
    pips: 23.0,
    openTime: '14:28 UTC',
  },
  {
    id: '3',
    symbol: 'US100',
    side: 'SELL',
    size: 1.0,
    entryPrice: 20455.00,
    currentPrice: 20412.50,
    stopLoss: 20520.00,
    takeProfit: 20310.00,
    pnl: 42.50,
    pnlPercent: 0.21,
    pips: 42.5,
    openTime: '13:50 UTC',
  },
];

export const initialAlertConfig: AlertConfiguration = {
  newSignalAlerts: true,
  positionOpenedClosed: true,
  takeProfitHit: true,
  stopLossHit: true,
  dailySummaryEmail: 'trader.desk@quantview.capital',
  telegramBotHandle: '@signalTheBEST_bot',
  telegramChatConnected: true,
};

export const initialNewsEvents: NewsEvent[] = [
  {
    id: 110,
    time: '00:00 UTC',
    currency: 'JPY',
    event: 'Tokyo Core CPI y/y',
    impact: 'MEDIUM',
    actual: null,
    forecast: '2.1%',
    previous: '2.2%',
    minutesUntil: -180,
    isBlackoutTrigger: false,
    scheduledTimeRaw: '2026-09-01T00:00:00Z',
  },
  {
    id: 127,
    time: '00:00 UTC',
    currency: 'USD',
    event: 'Core CPI (MoM & YoY)',
    impact: 'HIGH',
    actual: null,
    forecast: '-0.2%',
    previous: '0.0%',
    minutesUntil: 24,
    isBlackoutTrigger: true,
    scheduledTimeRaw: new Date(Date.now() + 24 * 60 * 1000).toISOString(),
  },
  {
    id: 149,
    time: '09:00 UTC',
    currency: 'EUR',
    event: 'Core CPI Flash Estimate y/y',
    impact: 'MEDIUM',
    actual: null,
    forecast: '2.5%',
    previous: '2.5%',
    minutesUntil: 120,
    isBlackoutTrigger: false,
    scheduledTimeRaw: new Date(Date.now() + 120 * 60 * 1000).toISOString(),
  },
  {
    id: 145,
    time: '08:30 UTC',
    currency: 'GBP',
    event: 'Final Manufacturing PMI',
    impact: 'LOW',
    actual: null,
    forecast: '51.5',
    previous: '51.5',
    minutesUntil: 240,
    isBlackoutTrigger: false,
    scheduledTimeRaw: new Date(Date.now() + 240 * 60 * 1000).toISOString(),
  },
];

export const initialRiskStatus: RiskStatus = {
  isBlackout: false,
  statusText: 'SAFE TO TRADE — No immediate high-impact blackout in effect',
  allowedRiskPercent: 0.5,
  activeEvent: 'USD Core CPI in 24m (Blackout window: -30m / +15m)',
  minutesRemaining: 24,
};

export interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema20: number;
  ema50: number;
  ema200: number;
  fvgZone?: { top: number; bottom: number; type: 'bullish' | 'bearish' };
  isGreen: boolean;
}

export const generateCandles = (symbol: PairSymbol): CandleData[] => {
  let basePrice = 4410.00;
  let volatility = 8.5;
  let precision = 2;

  if (symbol === 'US100') {
    basePrice = 20450.00;
    volatility = 35.0;
    precision = 2;
  } else if (symbol === 'XAU/USD') {
    basePrice = 4410.00;
    volatility = 8.5;
    precision = 2;
  }

  const candles: CandleData[] = [];
  let currentClose = basePrice;
  const now = new Date();

  for (let i = 24; i >= 0; i--) {
    const timeStr = new Date(now.getTime() - i * 15 * 60 * 1000).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });

    const change = (Math.random() - 0.47) * volatility;
    const open = Number(currentClose.toFixed(precision));
    const close = Number((open + change).toFixed(precision));
    const high = Number((Math.max(open, close) + Math.random() * (volatility * 0.4)).toFixed(precision));
    const low = Number((Math.min(open, close) - Math.random() * (volatility * 0.4)).toFixed(precision));
    const volume = Math.floor(Math.random() * 8000 + 2000);

    const isGreen = close >= open;

    const ema20 = Number((close * 0.9994).toFixed(precision));
    const ema50 = Number((close * 0.9988).toFixed(precision));
    const ema200 = Number((close * 0.9972).toFixed(precision));

    const fvgZone = i === 6 ? {
      top: Number((high * 1.0004).toFixed(precision)),
      bottom: Number((low * 0.9996).toFixed(precision)),
      type: isGreen ? 'bullish' as const : 'bearish' as const
    } : undefined;

    candles.push({
      time: timeStr,
      open,
      high,
      low,
      close,
      volume,
      ema20,
      ema50,
      ema200,
      fvgZone,
      isGreen,
    });

    currentClose = close;
  }

  return candles;
};
