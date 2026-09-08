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
  balance: 8048.00,
  equity: 8071.52,
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
    id: 'SIG-USDJPY-01',
    symbol: 'USD/JPY',
    direction: 'SELL',
    confluenceScore: 76,
    timeframe: '15m',
    entryPrice: 154.35983,
    stopLoss: 154.84742,
    takeProfit1: 153.38466,
    takeProfit2: 152.89707,
    riskRewardRatio: '1:2.0',
    pipsAtRisk: 48.7,
    timestamp: 'Just now',
    setupReason: 'Confirmed Bearish BOS + Buy-Side Liquidity Sweep + Pin Bar Trigger',
    notifyEnabled: true,
    status: 'ACTIVE',
    hasActiveSignal: true,
  },
  {
    id: 'SIG-GBPUSD-02',
    symbol: 'GBP/USD',
    direction: 'BUY',
    confluenceScore: 85,
    timeframe: '30m',
    entryPrice: 1.35382,
    stopLoss: 1.34991,
    takeProfit1: 1.36164,
    takeProfit2: 1.36555,
    riskRewardRatio: '1:2.0',
    pipsAtRisk: 39.1,
    timestamp: '15m ago',
    setupReason: 'Bullish BOS + Sell-Side Sweep + Fresh Institutional Demand Zone',
    notifyEnabled: true,
    status: 'ACTIVE',
    hasActiveSignal: true,
  },
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
  },
  {
    id: 'SIG-EURUSD-04',
    symbol: 'EUR/USD',
    direction: 'BUY',
    confluenceScore: 78,
    timeframe: '1h',
    entryPrice: 1.16243,
    stopLoss: 1.15920,
    takeProfit1: 1.16890,
    takeProfit2: 1.17350,
    riskRewardRatio: '1:2.0',
    pipsAtRisk: 32.3,
    timestamp: 'Scanning...',
    setupReason: 'Asian Low Sweep + HTF Bullish Structure + FVG Entry',
    notifyEnabled: true,
    status: 'ACTIVE',
    hasActiveSignal: true,
  },
];

export const initialPositions: Position[] = [
  {
    id: '4',
    symbol: 'GBP/USD',
    side: 'BUY',
    size: 0.1,
    entryPrice: 1.35387,
    currentPrice: 1.35452,
    stopLoss: 1.34991,
    takeProfit: 1.36164,
    pnl: 6.50,
    pnlPercent: 0.05,
    pips: 6.5,
    openTime: '14:28 UTC',
  },
  {
    id: '3',
    symbol: 'USD/JPY',
    side: 'SELL',
    size: 0.02,
    entryPrice: 154.398,
    currentPrice: 153.547,
    stopLoss: 156.407,
    takeProfit: 150.394,
    pnl: 17.02,
    pnlPercent: 0.11,
    pips: 85.1,
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
  let basePrice = 1.1620;
  let volatility = 0.0015;
  let precision = 5;

  if (symbol === 'GBP/USD') {
    basePrice = 1.3530;
    volatility = 0.0020;
    precision = 5;
  } else if (symbol === 'USD/JPY') {
    basePrice = 153.70;
    volatility = 0.25;
    precision = 3;
  } else if (symbol === 'XAU/USD') {
    // REAL GOLD PRICE REGIME ~4410 - 4420
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
