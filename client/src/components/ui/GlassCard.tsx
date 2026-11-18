import React from 'react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  headerAction?: React.ReactNode;
  glowColor?: 'green' | 'red' | 'purple' | 'cyan' | 'none';
  id?: string;
}

export const GlassCard: React.FC<GlassCardProps> = ({
  children,
  className = '',
  title,
  subtitle,
  headerAction,
  glowColor = 'none',
  id,
}) => {
  const glowStyles = {
    none: '',
    green:
      'shadow-[0_0_35px_rgba(16,185,129,0.12)] border-emerald-500/20 hover:border-emerald-500/35 before:absolute before:inset-0 before:bg-gradient-to-b before:from-emerald-500/10 before:to-transparent before:pointer-events-none before:rounded-2xl',
    red:
      'shadow-[0_0_35px_rgba(244,63,94,0.12)] border-rose-500/20 hover:border-rose-500/35 before:absolute before:inset-0 before:bg-gradient-to-b before:from-rose-500/10 before:to-transparent before:pointer-events-none before:rounded-2xl',
    purple:
      'shadow-[0_0_35px_rgba(168,85,247,0.15)] border-purple-500/20 hover:border-purple-500/35 before:absolute before:inset-0 before:bg-gradient-to-b before:from-purple-500/10 before:to-transparent before:pointer-events-none before:rounded-2xl',
    cyan:
      'shadow-[0_0_35px_rgba(6,182,212,0.12)] border-cyan-500/20 hover:border-cyan-500/35 before:absolute before:inset-0 before:bg-gradient-to-b before:from-cyan-500/10 before:to-transparent before:pointer-events-none before:rounded-2xl',
  };

  return (
    <div
      id={id}
      className={cn(
        'relative bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl overflow-hidden',
        'transition-all duration-300 hover:border-white/20 hover:bg-white/[0.07]',
        glowStyles[glowColor],
        className
      )}
    >
      {/* Subtle top edge hairline highlight */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/20 to-transparent pointer-events-none" />

      {/* Header bar (rendered if title is provided) */}
      {title && (
        <div className="flex items-center justify-between px-4 sm:px-6 py-3.5 border-b border-white/10 relative z-10">
          <div>
            <h3 className="text-sm font-semibold text-slate-100 font-sans tracking-tight">
              {title}
            </h3>
            {subtitle && (
              <p className="text-xs text-slate-400 font-sans mt-0.5">{subtitle}</p>
            )}
          </div>
          {headerAction && (
            <div className="flex items-center gap-2">{headerAction}</div>
          )}
        </div>
      )}

      {/* Content wrapper */}
      <div className="relative z-10">{children}</div>
    </div>
  );
};

export default GlassCard;
