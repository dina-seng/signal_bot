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
  balance: 128450.00,
  equity: 132185.50,
  unrealizedPnl: 3735.50,
  unrealizedPnlPercent: 2.91,
  marginUsed: 14200.00,
  marginAvailable: 117985.50,
  marginLevelPercent: 930.88,
  activePositionsCount: 4,
  todayPnl: 1845.20,
  brokerStatus: 'CONNECTED',
  latencyMs: 14,
};

export const initialPerformanceStats: PerformanceStats = {
  winRate: 69.4,
  winRateDelta: 2.3,
  profitFactor: 2.38,
  profitFactorDelta: 0.14,
  totalTrades: 412,
  totalTradesDelta: 18,
  maxDrawdown: 4.6,
  maxDrawdownDelta: -0.4,
  sharpeRatio: 2.14,
  expectancyPips: 18.6,
};

export const equityHistoryData: Record<'1W' | '1M' | '3M' | 'ALL', EquityDataPoint[]> = {
  '1W': [
    { timestamp: 'Mon 00:00', equity: 129400, balance: 128200, drawdown: 0.4 },
    { timestamp: 'Mon 12:00', equity: 129850, balance: 128200, drawdown: 0.2 },
    { timestamp: 'Tue 00:00', equity: 130320, balance: 128450, drawdown: 0.1 },
    { timestamp: 'Tue 12:00', equity: 129980, balance: 128450, drawdown: 0.7 },
    { timestamp: 'Wed 00:00', equity: 130750, balance: 128450, drawdown: 0.2 },
    { timestamp: 'Wed 12:00', equity: 131200, balance: 128450, drawdown: 0.1 },
    { timestamp: 'Thu 00:00', equity: 131050, balance: 128450, drawdown: 0.4 },
    { timestamp: 'Thu 12:00', equity: 131680, balance: 128450, drawdown: 0.1 },
    { timestamp: 'Fri 00:00', equity: 131920, balance: 128450, drawdown: 0.1 },
    { timestamp: 'Today', equity: 132185.50, balance: 128450, drawdown: 0.0 },
  ],
  '1M': [
    { timestamp: 'Week 1', equity: 122100, balance: 121500, drawdown: 1.2 },
    { timestamp: 'Week 2', equity: 124800, balance: 123900, drawdown: 0.8 },
    { timestamp: 'Week 3', equity: 127200, balance: 126100, drawdown: 0.5 },
    { timestamp: 'Week 4', equity: 129600, balance: 128100, drawdown: 0.9 },
    { timestamp: 'Current', equity: 132185.50, balance: 128450, drawdown: 0.0 },
  ],
  '3M': [
    { timestamp: 'Jul W1', equity: 112000, balance: 110000, drawdown: 2.1 },
    { timestamp: 'Jul W3', equity: 115400, balance: 114000, drawdown: 1.5 },
    { timestamp: 'Aug W1', equity: 119800, balance: 118000, drawdown: 1.8 },
    { timestamp: 'Aug W3', equity: 124200, balance: 123100, drawdown: 0.9 },
    { timestamp: 'Sep W1', equity: 128900, balance: 127500, drawdown: 0.6 },
    { timestamp: 'Current', equity: 132185.50, balance: 128450, drawdown: 0.0 },
  ],
  'ALL': [
    { timestamp: 'Jan', equity: 100000, balance: 100000, drawdown: 0.0 },
    { timestamp: 'Feb', equity: 103800, balance: 103000, drawdown: 1.1 },
    { timestamp: 'Mar', equity: 107500, balance: 106200, drawdown: 2.4 },
    { timestamp: 'Apr', equity: 111200, balance: 109800, drawdown: 1.5 },
    { timestamp: 'May', equity: 116800, balance: 115200, drawdown: 3.2 },
    { timestamp: 'Jun', equity: 121000, balance: 119500, drawdown: 1.8 },
    { timestamp: 'Jul', equity: 124500, balance: 123000, drawdown: 2.0 },
    { timestamp: 'Aug', equity: 128900, balance: 127400, drawdown: 1.2 },
    { timestamp: 'Sep', equity: 132185.50, balance: 128450, drawdown: 0.0 },
  ],
};

export const initialSignals: TradeSignal[] = [
  {
    id: 'SIG-EURUSD-01',
    symbol: 'EUR/USD',
    direction: 'BUY',
    confluenceScore: 88,
    timeframe: '15m / 1h',
    entryPrice: 1.08450,
    stopLoss: 1.08180,
    takeProfit1: 1.08980,
    takeProfit2: 1.09400,
    riskRewardRatio: '1:3.4',
    pipsAtRisk: 27.0,
    timestamp: '5m ago',
    setupReason: 'Asian Low Sweep + 15m Bullish CHOCH + Unmitigated FVG',
    notifyEnabled: true,
    status: 'ACTIVE',
  },
  {
    id: 'SIG-GBPUSD-02',
    symbol: 'GBP/USD',
    direction: 'SELL',
    confluenceScore: 82,
    timeframe: '1h',
    entryPrice: 1.29340,
    stopLoss: 1.29650,
    takeProfit1: 1.28720,
    takeProfit2: 1.28200,
    riskRewardRatio: '1:3.7',
    pipsAtRisk: 31.0,
    timestamp: '14m ago',
    setupReason: 'London High Liquidity Run + 1h Bearish Order Block Reject',
    notifyEnabled: true,
    status: 'ACTIVE',
  },
  {
    id: 'SIG-USDJPY-03',
    symbol: 'USD/JPY',
    direction: 'BUY',
    confluenceScore: 78,
    timeframe: '4h / 1h',
    entryPrice: 154.220,
    stopLoss: 153.800,
    takeProfit1: 155.100,
    takeProfit2: 155.800,
    riskRewardRatio: '1:3.8',
    pipsAtRisk: 42.0,
    timestamp: '28m ago',
    setupReason: 'Daily Demand Zone Bounce + RSI Bullish Divergence',
    notifyEnabled: false,
    status: 'ACTIVE',
  },
  {
    id: 'SIG-XAUUSD-04',
    symbol: 'XAU/USD',
    direction: 'BUY',
    confluenceScore: 94,
    timeframe: '30m / 4h',
    entryPrice: 2364.50,
    stopLoss: 2351.00,
    takeProfit1: 2391.50,
    takeProfit2: 2415.00,
    riskRewardRatio: '1:3.7',
    pipsAtRisk: 135.0,
    timestamp: '3m ago',
    setupReason: 'Triple Confluence: HTF Trend Continuation + FVG Reaction + DXY Weakness',
    notifyEnabled: true,
    status: 'ACTIVE',
  },
];

export const initialPositions: Position[] = [
  {
    id: 'POS-001',
    symbol: 'EUR/USD',
    side: 'BUY',
    size: 2.5,
    entryPrice: 1.08210,
    currentPrice: 1.08455,
    stopLoss: 1.07950,
    takeProfit: 1.08980,
    pnl: 612.50,
    pnlPercent: 0.48,
    pips: 24.5,
    openTime: '10:14 UTC',
  },
  {
    id: 'POS-002',
    symbol: 'GBP/USD',
    side: 'SELL',
    size: 3.0,
    entryPrice: 1.29580,
    currentPrice: 1.29340,
    stopLoss: 1.29900,
    takeProfit: 1.28720,
    pnl: 720.00,
    pnlPercent: 0.56,
    pips: 24.0,
    openTime: '08:45 UTC',
  },
  {
    id: 'POS-003',
    symbol: 'XAU/USD',
    side: 'BUY',
    size: 1.5,
    entryPrice: 2348.20,
    currentPrice: 2364.50,
    stopLoss: 2338.00,
    takeProfit: 2391.50,
    pnl: 2445.00,
    pnlPercent: 1.90,
    pips: 163.0,
    openTime: '06:30 UTC',
  },
  {
    id: 'POS-004',
    symbol: 'USD/JPY',
    side: 'SELL',
    size: 2.0,
    entryPrice: 154.450,
    currentPrice: 154.510,
    stopLoss: 154.800,
    takeProfit: 153.800,
    pnl: -78.00,
    pnlPercent: -0.06,
    pips: -6.0,
    openTime: '11:02 UTC',
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
    id: 'NEWS-01',
    time: '13:30 UTC',
    currency: 'USD',
    event: 'Core CPI (MoM & YoY)',
    impact: 'HIGH',
    actual: undefined,
    forecast: '0.3%',
    previous: '0.2%',
    minutesUntil: 24,
    isBlackoutTrigger: true,
  },
  {
    id: 'NEWS-02',
    time: '14:45 UTC',
    currency: 'USD',
    event: 'Flash Manufacturing PMI',
    impact: 'MEDIUM',
    actual: undefined,
    forecast: '50.1',
    previous: '49.8',
    minutesUntil: 99,
    isBlackoutTrigger: false,
  },
  {
    id: 'NEWS-03',
    time: '11:00 UTC',
    currency: 'EUR',
    event: 'ECB Monetary Policy Minutes',
    impact: 'HIGH',
    actual: 'Hawkish Tilt',
    forecast: '--',
    previous: '--',
    minutesUntil: -126,
    isBlackoutTrigger: false,
  },
  {
    id: 'NEWS-04',
    time: '07:00 UTC',
    currency: 'GBP',
    event: 'Retail Sales MoM',
    impact: 'HIGH',
    actual: '+0.5%',
    forecast: '+0.2%',
    previous: '-0.3%',
    minutesUntil: -366,
    isBlackoutTrigger: false,
  },
];

export const initialRiskStatus: RiskStatus = {
  isBlackout: false,
  statusText: 'SAFE TO TRADE — No immediate high-impact blackout in effect',
  allowedRiskPercent: 0.5,
  activeEvent: 'USD Core CPI in 24m (Blackout window: -30m / +15m)',
  minutesRemaining: 24,
};

// Generates candlestick data for the interactive chart placeholder
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
  let basePrice = 1.0800;
  let volatility = 0.0015;
  let precision = 5;

  if (symbol === 'GBP/USD') {
    basePrice = 1.2900;
    volatility = 0.0020;
    precision = 5;
  } else if (symbol === 'USD/JPY') {
    basePrice = 154.00;
    volatility = 0.35;
    precision = 3;
  } else if (symbol === 'XAU/USD') {
    basePrice = 2350.00;
    volatility = 6.5;
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

    // Simulated EMA values
    const ema20 = Number((close * 0.9992).toFixed(precision));
    const ema50 = Number((close * 0.9984).toFixed(precision));
    const ema200 = Number((close * 0.9965).toFixed(precision));

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
