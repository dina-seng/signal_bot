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
  balance: 0,
  equity: 0,
  unrealizedPnl: 0,
  unrealizedPnlPercent: 0,
  marginUsed: 0,
  marginAvailable: 0,
  marginLevelPercent: 0,
  activePositionsCount: 0,
  todayPnl: 0,
  brokerStatus: 'RECONNECTING',
  latencyMs: 0,
};

export const initialPerformanceStats: PerformanceStats = {
  winRate: 0,
  winRateDelta: 0,
  profitFactor: 0,
  profitFactorDelta: 0,
  totalTrades: 0,
  totalTradesDelta: 0,
  maxDrawdown: null,
  maxDrawdownDelta: 0,
  sharpeRatio: null,
  expectancyPips: null,
  initialBalance: null,
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
    id: 'SIG-XAUUSD-INIT',
    symbol: 'XAU/USD',
    direction: 'SCANNING',
    confluenceScore: 0,
    timeframe: '15m',
    currentPrice: undefined,
    notifyEnabled: false,
    status: 'SCANNING',
    hasActiveSignal: false,
    setupReason: 'Awaiting Data: Connecting to market feed...',
  },
];

export const initialPositions: Position[] = [];

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

export const generateCandles = (_symbol: PairSymbol): CandleData[] => [];
