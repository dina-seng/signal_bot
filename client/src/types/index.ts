export type TradeDirection = 'BUY' | 'SELL';

export type PairSymbol = 'EUR/USD' | 'GBP/USD' | 'USD/JPY' | 'XAU/USD';

export interface PerformanceStats {
  winRate: number; // e.g. 68.4
  winRateDelta: number; // e.g. +2.1%
  profitFactor: number; // e.g. 2.45
  profitFactorDelta: number;
  totalTrades: number; // e.g. 342
  totalTradesDelta: number;
  maxDrawdown: number; // e.g. 4.8%
  maxDrawdownDelta: number;
  sharpeRatio: number;
  expectancyPips: number;
}

export interface EquityDataPoint {
  timestamp: string;
  equity: number;
  balance: number;
  drawdown: number;
}

export interface TradeSignal {
  id: string;
  symbol: PairSymbol;
  direction: TradeDirection;
  confluenceScore: number; // 0 - 100
  timeframe: string;
  entryPrice: number;
  stopLoss: number;
  takeProfit1: number;
  takeProfit2: number;
  riskRewardRatio: string;
  pipsAtRisk: number;
  timestamp: string;
  setupReason: string;
  notifyEnabled: boolean;
  status: 'ACTIVE' | 'PENDING' | 'TRIGGERED';
}

export interface Position {
  id: string;
  symbol: PairSymbol;
  side: TradeDirection;
  size: number; // in lots
  entryPrice: number;
  currentPrice: number;
  stopLoss: number;
  takeProfit: number;
  pnl: number; // in USD
  pnlPercent: number;
  pips: number;
  openTime: string;
}

export interface NewsEvent {
  id: string;
  time: string;
  currency: string;
  event: string;
  impact: 'HIGH' | 'MEDIUM' | 'LOW';
  actual?: string;
  forecast: string;
  previous: string;
  minutesUntil: number;
  isBlackoutTrigger: boolean;
}

export interface RiskStatus {
  isBlackout: boolean;
  statusText: string;
  activeEvent?: string;
  minutesRemaining?: number;
  allowedRiskPercent: number;
}

export interface AlertConfiguration {
  newSignalAlerts: boolean;
  positionOpenedClosed: boolean;
  takeProfitHit: boolean;
  stopLossHit: boolean;
  dailySummaryEmail: string;
  telegramBotHandle: string;
  telegramChatConnected: boolean;
}

export interface AccountSummary {
  balance: number;
  equity: number;
  unrealizedPnl: number;
  unrealizedPnlPercent: number;
  marginUsed: number;
  marginAvailable: number;
  marginLevelPercent: number;
  activePositionsCount: number;
  todayPnl: number;
  brokerStatus: 'CONNECTED' | 'RECONNECTING' | 'OFFLINE';
  latencyMs: number;
}

export type NavigationTab = 'dashboard' | 'signals' | 'positions' | 'news' | 'settings';
