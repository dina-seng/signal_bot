import React from 'react';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  interactive?: boolean;
  glowOnHover?: 'emerald' | 'violet' | 'rose' | 'none';
  specularSheen?: boolean;
}

export const Card: React.FC<CardProps> = ({
  children,
  className = '',
  interactive = true,
  glowOnHover = 'none',
  specularSheen = true,
  ...props
}) => {
  // Configurable dynamic glow styles
  const glowClasses = {
    none: 'hover:border-white/20 hover:shadow-[0_20px_45px_-12px_rgba(0,0,0,0.8),inset_0_1px_0_rgba(255,255,255,0.12)]',
    emerald: 'hover:border-emerald-500/30 hover:shadow-[0_20px_45px_-12px_rgba(0,0,0,0.8),0_0_30px_-5px_rgba(16,185,129,0.18),inset_0_1px_0_rgba(255,255,255,0.15)]',
    violet: 'hover:border-violet-500/30 hover:shadow-[0_20px_45px_-12px_rgba(0,0,0,0.8),0_0_30px_-5px_rgba(139,92,246,0.18),inset_0_1px_0_rgba(255,255,255,0.15)]',
    rose: 'hover:border-rose-500/30 hover:shadow-[0_20px_45px_-12px_rgba(0,0,0,0.8),0_0_30px_-5px_rgba(244,63,94,0.18),inset_0_1px_0_rgba(255,255,255,0.15)]',
  }[glowOnHover];

  return (
    <div
      className={`group relative overflow-hidden rounded-2xl bg-white/[0.04] backdrop-blur-xl border border-white/10 shadow-[0_20px_40px_-15px_rgba(0,0,0,0.7),inset_0_1px_0_rgba(255,255,255,0.08)] ${
        interactive
          ? `transition-all duration-500 ease-out hover:-translate-y-1 hover:bg-white/[0.06] ${glowClasses}`
          : ''
      } ${className}`}
      {...props}
    >
      {/* Specular top-edge highlight that cleanly detaches card from animated mesh */}
      {specularSheen && (
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/20 to-transparent opacity-40 transition-opacity duration-500 group-hover:opacity-100" />
      )}

      {children}
    </div>
  );
};
