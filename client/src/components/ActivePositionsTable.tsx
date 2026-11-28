import React, { useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  XCircle,
  Clock,
  History,
  Briefcase,
  CheckCircle,
  AlertOctagon,
  Award,
} from 'lucide-react';
import { Position, ClosedTrade } from '../types';
import { formatPrice, formatPnL } from '../utils/formatters';

interface ActivePositionsTableProps {
  positions: Position[];
  closedTrades?: ClosedTrade[];
  isLoading?: boolean;
  onClosePosition: (id: string, symbol: string) => void;
}

export const ActivePositionsTable: React.FC<ActivePositionsTableProps> = ({
  positions,
  closedTrades = [],
  isLoading = false,
  onClosePosition,
}) => {
  const [activeTab, setActiveTab] = useState<'open' | 'closed'>('open');

  const totalFloatingPnl = positions.reduce((acc, p) => acc + (p.pnl || 0), 0);
  const totalFloatingPnlFormatted = formatPnL(totalFloatingPnl);

  const totalRealizedPnl = closedTrades.reduce((acc, t) => acc + (t.realizedPnl || 0), 0);
  const totalRealizedPnlFormatted = formatPnL(totalRealizedPnl);

  const winningTrades = closedTrades.filter((t) => t.realizedPnl > 0).length;
  const winRate = closedTrades.length > 0
    ? ((winningTrades / closedTrades.length) * 100).toFixed(1)
    : '0.0';

  return (
    <div className="space-y-3 font-mono min-w-0 w-full overflow-hidden">
      {/* Top Header & Tab Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-white tracking-wide uppercase">Position Ledger</h2>
          <div className="flex items-center p-0.5 rounded bg-[#0a0b10] border border-[#1d2230]">
            <button
              onClick={() => setActiveTab('open')}
              className={`min-h-[44px] md:min-h-0 px-2.5 py-1 rounded text-xs font-bold transition-colors flex items-center gap-1.5 cursor-pointer ${
                activeTab === 'open'
                  ? 'bg-[#161922] text-cyan-400 border border-[#1d2230]'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <Briefcase className="w-3 h-3" />
              <span>Open Positions ({positions.length})</span>
            </button>
            <button
              onClick={() => setActiveTab('closed')}
              className={`min-h-[44px] md:min-h-0 px-2.5 py-1 rounded text-xs font-bold transition-colors flex items-center gap-1.5 cursor-pointer ${
                activeTab === 'closed'
                  ? 'bg-[#161922] text-[#00e676] border border-[#1d2230]'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <History className="w-3 h-3" />
              <span>History ({closedTrades.length})</span>
            </button>
          </div>
        </div>

        {/* Floating/Realized summary badge */}
        <div className="flex items-center gap-2 text-xs">
          {activeTab === 'open' ? (
            <div className="px-2.5 py-1 rounded bg-[#0a0b10] border border-[#1d2230] flex items-center gap-2">
              <span className="text-[10px] text-slate-500 uppercase">Floating P&L:</span>
              <span className={`font-bold ${totalFloatingPnlFormatted.colorClass}`}>
                {totalFloatingPnlFormatted.formatted}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 flex-wrap">
              <div className="px-2.5 py-1 rounded bg-[#0a0b10] border border-[#1d2230] flex items-center gap-2">
                <span className="text-[10px] text-slate-500 uppercase">Realized P&L:</span>
                <span className={`font-bold ${totalRealizedPnlFormatted.colorClass}`}>
                  {totalRealizedPnlFormatted.formatted}
                </span>
              </div>
              <div className="px-2.5 py-1 rounded bg-[#0a0b10] border border-[#1d2230] flex items-center gap-1.5 text-slate-400">
                <Award className="w-3 h-3 text-amber-400" />
                <span>Win: <strong className="text-white">{winRate}%</strong> ({winningTrades}/{closedTrades.length})</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Table Container - Scrollable without breaking page boundaries */}
      <div className="overflow-x-auto rounded-2xl border border-white/10 bg-zinc-900/40 backdrop-blur-md min-w-0 w-full shadow-xl">
        {activeTab === 'open' ? (
          /* OPEN POSITIONS TABLE */
          <table className="w-full min-w-[640px] text-left text-xs">
            <thead className="bg-[#0c0d12] text-slate-500 uppercase text-[10px] tracking-wider border-b border-[#1d2230]">
              <tr>
                <th scope="col" className="py-2.5 px-3.5">Pair</th>
                <th scope="col" className="py-2.5 px-3.5">Account</th>
                <th scope="col" className="py-2.5 px-3.5">Side</th>
                <th scope="col" className="hidden md:table-cell py-2.5 px-3.5 text-right">Size</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">Entry</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">Current</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">SL</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">TP</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">P&L ($ / Pips)</th>
                <th scope="col" className="py-2.5 px-3.5 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1d2230]/60 text-[11px]">
              {positions.length === 0 ? (
                <tr>
                  <td colSpan={10} className="py-8 text-center text-slate-500 italic text-xs">
                    No active positions open in database. (Execute signals or trigger scanner to open paper orders)
                  </td>
                </tr>
              ) : (
                positions.map((pos) => {
                  const isBuy = pos.side === 'BUY';
                  const pnlMeta = formatPnL(pos.pnl);

                  return (
                    <tr
                      key={pos.id}
                      className="hover:bg-[#161922]/50 transition-colors"
                    >
                      {/* Pair */}
                      <td className="py-2.5 px-3.5 font-bold text-white whitespace-nowrap">
                        <span className="text-slate-100">{pos.symbol}</span>
                        <span className="text-[10px] text-slate-500 font-normal ml-1.5">
                          {pos.openTime}
                        </span>
                      </td>

                      {/* Executing account */}
                      <td className="py-2.5 px-3.5 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                            (pos.account || 'MAIN') === 'CENT'
                              ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                              : 'bg-violet-500/10 text-violet-300 border-violet-500/30'
                          }`}
                          title={`Executing Exness account: ${pos.account || 'MAIN'}`}
                        >
                          {pos.account || 'MAIN'}
                        </span>
                      </td>

                      {/* Side */}
                      <td className="py-2.5 px-3.5 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                            isBuy
                              ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                              : 'bg-[#ff3366]/10 text-[#ff3366] border-[#ff3366]/30'
                          }`}
                        >
                          {isBuy ? (
                            <TrendingUp className="w-2.5 h-2.5" />
                          ) : (
                            <TrendingDown className="w-2.5 h-2.5" />
                          )}
                          {pos.side}
                        </span>
                      </td>

                      {/* Size */}
                      <td className="hidden md:table-cell py-2.5 px-3.5 text-right text-slate-200">
                        {pos.size.toFixed(2)}L
                      </td>

                      {/* Entry Price */}
                      <td className="py-2.5 px-3.5 text-right text-slate-400">
                        {formatPrice(pos.symbol, pos.entryPrice)}
                      </td>

                      {/* Current Price */}
                      <td className="py-2.5 px-3.5 text-right font-bold text-slate-200">
                        <span className="px-1 py-0.5 rounded bg-[#0a0b10] border border-[#1d2230]">
                          {formatPrice(pos.symbol, pos.currentPrice)}
                        </span>
                      </td>

                      {/* SL */}
                      <td className="py-2.5 px-3.5 text-right text-[#ff3366]">
                        {formatPrice(pos.symbol, pos.stopLoss)}
                      </td>

                      {/* TP */}
                      <td className="py-2.5 px-3.5 text-right text-[#00e676]">
                        {formatPrice(pos.symbol, pos.takeProfit)}
                      </td>

                      {/* P&L */}
                      <td className="py-2.5 px-3.5 text-right whitespace-nowrap">
                        <div
                          className={`font-bold flex items-center justify-end gap-1 ${pnlMeta.colorClass}`}
                        >
                          <span>{pnlMeta.formatted}</span>
                          <span className="text-[10px] opacity-75">
                            ({pos.pips >= 0 ? '+' : ''}
                            {pos.pips.toFixed(1)}p)
                          </span>
                        </div>
                      </td>

                      {/* Action */}
                      <td className="py-2.5 px-3.5 text-center">
                        <button
                          onClick={() => onClosePosition(pos.id, pos.symbol)}
                          className="flex min-h-[44px] min-w-[44px] md:min-h-0 md:min-w-0 items-center justify-center p-1 rounded bg-[#161922] hover:bg-[#ff3366]/20 text-slate-400 hover:text-[#ff3366] border border-[#1d2230] hover:border-[#ff3366]/40 transition-colors cursor-pointer"
                          title={`Close ${pos.symbol} position #${pos.id}`}
                        >
                          <XCircle className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        ) : (
          /* CLOSED TRADES HISTORY TABLE */
          <table className="w-full min-w-[640px] text-left text-xs">
            <thead className="bg-[#0c0d12] text-slate-500 uppercase text-[10px] tracking-wider border-b border-[#1d2230]">
              <tr>
                <th scope="col" className="py-2.5 px-3.5">ID / Pair</th>
                <th scope="col" className="py-2.5 px-3.5">Account</th>
                <th scope="col" className="py-2.5 px-3.5">Side</th>
                <th scope="col" className="hidden md:table-cell py-2.5 px-3.5 text-right">Size</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">Entry</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">Exit</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">Realized P&L</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">Pips</th>
                <th scope="col" className="py-2.5 px-3.5 text-center">Exit Reason</th>
                <th scope="col" className="py-2.5 px-3.5 text-right">Closed (UTC)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1d2230]/60 text-[11px]">
              {closedTrades.length === 0 ? (
                <tr>
                  <td colSpan={10} className="py-8 text-center text-slate-500 italic text-xs">
                    No closed trades recorded in backend history yet.
                  </td>
                </tr>
              ) : (
                closedTrades.map((trade) => {
                  const isBuy = trade.side === 'BUY';
                  const isProfit = trade.realizedPnl >= 0;
                  const pnlMeta = formatPnL(trade.realizedPnl);

                  return (
                    <tr
                      key={trade.id}
                      className="hover:bg-[#161922]/50 transition-colors"
                    >
                      {/* ID / Pair */}
                      <td className="py-2.5 px-3.5 whitespace-nowrap">
                        <span className="text-slate-500 text-[10px] mr-1.5">#{trade.id}</span>
                        <span className="font-bold text-slate-200">{trade.symbol}</span>
                      </td>

                      {/* Executing account */}
                      <td className="py-2.5 px-3.5 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                            (trade.account || 'MAIN') === 'CENT'
                              ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                              : 'bg-violet-500/10 text-violet-300 border-violet-500/30'
                          }`}
                          title={`Executing Exness account: ${trade.account || 'MAIN'}`}
                        >
                          {trade.account || 'MAIN'}
                        </span>
                      </td>

                      {/* Side */}
                      <td className="py-2.5 px-3.5 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                            isBuy
                              ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                              : 'bg-[#ff3366]/10 text-[#ff3366] border-[#ff3366]/30'
                          }`}
                        >
                          {trade.side}
                        </span>
                      </td>

                      {/* Size */}
                      <td className="hidden md:table-cell py-2.5 px-3.5 text-right text-slate-300">
                        {trade.size.toFixed(2)}L
                      </td>

                      {/* Entry */}
                      <td className="py-2.5 px-3.5 text-right text-slate-400">
                        {formatPrice(trade.symbol, trade.entryPrice)}
                      </td>

                      {/* Exit Price */}
                      <td className="py-2.5 px-3.5 text-right font-bold text-slate-200">
                        {trade.exitPrice ? formatPrice(trade.symbol, trade.exitPrice) : '--'}
                      </td>

                      {/* Realized P&L */}
                      <td className="py-2.5 px-3.5 text-right whitespace-nowrap font-bold">
                        <span className={isProfit ? 'text-[#00e676]' : 'text-[#ff3366]'}>
                          {pnlMeta.formatted}
                        </span>
                      </td>

                      {/* Pips */}
                      <td className="py-2.5 px-3.5 text-right">
                        <span className={trade.pnlPips >= 0 ? 'text-[#00e676]' : 'text-[#ff3366]'}>
                          {trade.pnlPips >= 0 ? '+' : ''}{trade.pnlPips.toFixed(1)}p
                        </span>
                      </td>

                      {/* Exit Reason */}
                      <td className="py-2.5 px-3.5 text-center whitespace-nowrap">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${
                            trade.exitReason?.includes('TP')
                              ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                              : trade.exitReason?.includes('SL')
                              ? 'bg-[#ff3366]/10 text-[#ff3366] border-[#ff3366]/30'
                              : 'bg-[#161922] text-slate-400 border-[#1d2230]'
                          }`}
                        >
                          {trade.exitReason || 'CLOSED'}
                        </span>
                      </td>

                      {/* Closed Time */}
                      <td className="py-2.5 px-3.5 text-right text-slate-500 whitespace-nowrap text-[10px]">
                        {trade.closedAt
                          ? new Date(trade.closedAt).toLocaleString('en-GB', {
                              timeZone: 'UTC',
                              month: 'short',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit',
                            }) + ' UTC'
                          : '--'}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
