import React from 'react';
import { ArrowUpRight, ArrowDownRight, LucideIcon } from 'lucide-react';
import { Card } from './Card';

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
  const glow = isPositive ? 'emerald' : isNegative ? 'rose' : 'none';

  return (
    <Card
      title={tooltip}
      glowOnHover={glow}
      className="p-5 group w-full min-w-0 h-full flex flex-col justify-between"
    >
      <div>
        {/* Top Header Row */}
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium uppercase tracking-wider text-zinc-400 font-sans">
            {label}
          </span>
          <div
            className={`flex h-8 w-8 items-center justify-center rounded-xl border transition-transform duration-500 group-hover:scale-110 ${iconBg} ${iconColor}`}
          >
            <Icon className="h-4 w-4" />
          </div>
        </div>

        {/* Main Metric Value & Delta Badge */}
        <div className="mt-3 flex items-baseline gap-2.5">
          <span className="font-mono text-2xl font-semibold tracking-tight text-white drop-shadow-sm">
            {value}
          </span>

          {delta !== undefined && delta !== null && (
            <span
              className={`inline-flex items-center text-xs font-mono font-medium ${
                isPositive
                  ? 'text-emerald-400'
                  : isNegative
                  ? 'text-rose-500'
                  : 'text-zinc-400'
              }`}
            >
              {isPositive && <ArrowUpRight className="mr-0.5 h-3.5 w-3.5" />}
              {isNegative && <ArrowDownRight className="mr-0.5 h-3.5 w-3.5" />}
              {delta}
              {deltaLabel && <span className="ml-1 text-zinc-500 font-normal">{deltaLabel}</span>}
            </span>
          )}
        </div>
      </div>

      {/* Micro Context Footer */}
      {(subLabel || subValue) && (
        <div className="mt-4 flex items-center justify-between border-t border-white/5 pt-2.5 text-[11px] font-mono">
          <span className="text-zinc-500 font-sans">{subLabel}</span>
          <span className="font-medium text-zinc-300">{subValue}</span>
        </div>
      )}
    </Card>
  );
};
