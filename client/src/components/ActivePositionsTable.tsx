import React from 'react';
import {
  TrendingUp,
  TrendingDown,
  XCircle,
  Clock,
  ArrowUpDown,
  DollarSign,
  Shield,
  Target,
  Layers,
} from 'lucide-react';
import { Position } from '../types';
import { formatPrice, formatPnL } from '../utils/formatters';

interface ActivePositionsTableProps {
  positions: Position[];
  isLoading?: boolean;
  onClosePosition: (id: string, symbol: string) => void;
}

export const ActivePositionsTable: React.FC<ActivePositionsTableProps> = ({
  positions,
  isLoading = false,
  onClosePosition,
}) => {
  const totalPnl = positions.reduce((acc, p) => acc + (p.pnl || 0), 0);
  const totalPnlFormatted = formatPnL(totalPnl);

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-white">Active Positions</h2>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-cyan-500/15 text-cyan-400 border border-cyan-500/30 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
              Live 3s Polling
            </span>
          </div>
          <p className="text-xs text-slate-400 font-mono">
            Floating paper orders synchronized from SQLite database with dynamic SL/TP tracking
          </p>
        </div>

        {/* Floating summary */}
        <div className="flex items-center gap-3 text-xs font-mono">
          <div className="px-3 py-1.5 rounded-lg bg-[#181824] border border-[#1e1e2d] flex items-center gap-2">
            <span className="text-slate-400">Total Floating P&L:</span>
            <span className={`font-bold ${totalPnlFormatted.colorClass}`}>
              {totalPnlFormatted.formatted}
            </span>
          </div>
        </div>
      </div>

      {/* Table Container */}
      <div className="overflow-x-auto rounded-xl border border-[#1e1e2d] bg-[#12121a] shadow-terminal">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-[#0e0e16] text-slate-400 uppercase text-[10px] tracking-wider border-b border-[#1e1e2d]">
            <tr>
              <th scope="col" className="py-3 px-4">Pair</th>
              <th scope="col" className="py-3 px-4">Side</th>
              <th scope="col" className="py-3 px-4 text-right">Size (Lots)</th>
              <th scope="col" className="py-3 px-4 text-right">Entry Price</th>
              <th scope="col" className="py-3 px-4 text-right">Current Price</th>
              <th scope="col" className="py-3 px-4 text-right">Stop Loss</th>
              <th scope="col" className="py-3 px-4 text-right">Take Profit</th>
              <th scope="col" className="py-3 px-4 text-right">P&L ($ / Pips)</th>
              <th scope="col" className="py-3 px-4 text-center">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1e1e2d]/60">
            {positions.length === 0 ? (
              <tr>
                <td colSpan={9} className="py-8 text-center text-slate-500 italic">
                  No active trading positions open in database. (Execute signals or trigger scanner to open paper orders)
                </td>
              </tr>
            ) : (
              positions.map((pos) => {
                const isBuy = pos.side === 'BUY';
                const pnlMeta = formatPnL(pos.pnl);

                return (
                  <tr
                    key={pos.id}
                    className="hover:bg-[#181824]/60 transition-colors group"
                  >
                    {/* Pair */}
                    <td className="py-3 px-4 font-bold text-white flex items-center gap-2 whitespace-nowrap">
                      <span className="text-slate-100">{pos.symbol}</span>
                      <span className="text-[10px] text-slate-500 font-normal">
                        ({pos.openTime})
                      </span>
                    </td>

                    {/* Side */}
                    <td className="py-3 px-4 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold border ${
                          isBuy
                            ? 'bg-[#00ff88]/15 text-[#00ff88] border-[#00ff88]/30'
                            : 'bg-[#ff3366]/15 text-[#ff3366] border-[#ff3366]/30'
                        }`}
                      >
                        {isBuy ? (
                          <TrendingUp className="w-3 h-3" />
                        ) : (
                          <TrendingDown className="w-3 h-3" />
                        )}
                        {pos.side}
                      </span>
                    </td>

                    {/* Size */}
                    <td className="py-3 px-4 text-right text-slate-200 font-semibold">
                      {pos.size.toFixed(2)}
                    </td>

                    {/* Entry Price */}
                    <td className="py-3 px-4 text-right text-slate-300">
                      {formatPrice(pos.symbol, pos.entryPrice)}
                    </td>

                    {/* Current Price */}
                    <td className="py-3 px-4 text-right font-bold text-slate-100">
                      <span className="inline-block px-1.5 py-0.5 rounded bg-[#0a0a0f] border border-[#1e1e2d]">
                        {formatPrice(pos.symbol, pos.currentPrice)}
                      </span>
                    </td>

                    {/* SL */}
                    <td className="py-3 px-4 text-right text-[#ff3366]">
                      {formatPrice(pos.symbol, pos.stopLoss)}
                    </td>

                    {/* TP */}
                    <td className="py-3 px-4 text-right text-[#00ff88]">
                      {formatPrice(pos.symbol, pos.takeProfit)}
                    </td>

                    {/* P&L */}
                    <td className="py-3 px-4 text-right whitespace-nowrap">
                      <div
                        className={`font-bold flex items-center justify-end gap-1 ${pnlMeta.colorClass}`}
                      >
                        <span>{pnlMeta.formatted}</span>
                        <span className="text-[10px] opacity-80">
                          ({pos.pips >= 0 ? '+' : ''}
                          {pos.pips.toFixed(1)}p)
                        </span>
                      </div>
                    </td>

                    {/* Action */}
                    <td className="py-3 px-4 text-center">
                      <button
                        onClick={() => onClosePosition(pos.id, pos.symbol)}
                        className="p-1.5 rounded-lg bg-[#181824] hover:bg-[#ff3366]/20 text-slate-400 hover:text-[#ff3366] border border-[#1e1e2d] hover:border-[#ff3366]/40 transition-all cursor-pointer"
                        title={`Close ${pos.symbol} position #${pos.id}`}
                      >
                        <XCircle className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
