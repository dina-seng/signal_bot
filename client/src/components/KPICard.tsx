import React from 'react';
import { ArrowUpRight, ArrowDownRight, LucideIcon } from 'lucide-react';

export interface KPICardProps {
  label: string;
  value: string | number;
  delta?: number | string | null;
  deltaType?: 'positive' | 'negative' | 'neutral';
  deltaLabel?: string;
  icon: LucideIcon;
  iconColor?: string;
  iconBg?: string;
  subLabel?: string;
  subValue?: string | number;
  tooltip?: string;
}

export const KPICard: React.FC<KPICardProps> = ({
  label,
  value,
  delta,
  deltaType = 'positive',
  deltaLabel,
  icon: Icon,
  iconColor = 'text-emerald-400',
  iconBg = 'bg-emerald-500/10 border-emerald-500/20',
  subLabel,
  subValue,
  tooltip,
}) => {
  const isPositive = deltaType === 'positive';
  const isNegative = deltaType === 'negative';

  return (
    <div
      title={tooltip}
      className="group relative overflow-hidden rounded-2xl bg-zinc-900/40 backdrop-blur-md border border-white/10 p-4 transition-all duration-300 hover:bg-white/[0.06] hover:border-white/20 hover:shadow-[0_0_25px_rgba(255,255,255,0.04)]"
    >
      {/* Subtle Linear-style top edge specular highlight */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/20 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />

      {/* Top Header Row */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wider text-zinc-400">
          {label}
        </span>
        <div
          className={`flex h-8 w-8 items-center justify-center rounded-xl border transition-transform duration-300 group-hover:scale-105 ${iconBg} ${iconColor}`}
        >
          <Icon className="h-4 w-4" />
        </div>
      </div>

      {/* Main Metric Value & Delta Badge */}
      <div className="mt-3 flex items-baseline gap-2.5">
        <span className="font-mono text-2xl font-semibold tracking-tight text-white">
          {value}
        </span>

        {delta !== undefined && delta !== null && (
          <span
            className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 font-mono text-[11px] font-medium border ${
              isPositive
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : isNegative
                ? 'bg-rose-500/10 text-rose-500 border-rose-500/20'
                : 'bg-zinc-800/60 text-zinc-400 border-white/10'
            }`}
          >
            {isPositive && <ArrowUpRight className="h-3 w-3" />}
            {isNegative && <ArrowDownRight className="h-3 w-3" />}
            <span>{typeof delta === 'number' && delta > 0 ? `+${delta}` : delta}</span>
            {deltaLabel && <span className="opacity-75">{deltaLabel}</span>}
          </span>
        )}
      </div>

      {/* Footer Sub-metric (e.g. sample size, gross win/loss, expectancy) */}
      {(subLabel || subValue) && (
        <div className="mt-3.5 flex items-center justify-between border-t border-white/[0.06] pt-2 font-mono text-[11px]">
          <span className="text-zinc-500">{subLabel}</span>
          <span className="font-medium text-zinc-300">{subValue}</span>
        </div>
      )}
    </div>
  );
};
