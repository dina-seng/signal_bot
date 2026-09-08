/**
 * Formatting utilities for QuantView trading terminal
 */

/**
 * Format price according to symbol specification:
 * - Gold (XAU / GOLD): 2 decimals
 * - JPY pairs: 3 decimals
 * - Standard Forex: 5 decimals
 */
export function formatPrice(symbol: string = '', price: number | null | undefined): string {
  if (price === null || price === undefined || isNaN(price)) {
    return '--';
  }
  const sym = symbol.toUpperCase();
  if (sym.includes('XAU') || sym.includes('GOLD')) {
    return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (sym.includes('JPY')) {
    return price.toLocaleString('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  }
  return price.toLocaleString('en-US', { minimumFractionDigits: 5, maximumFractionDigits: 5 });
}

/**
 * Format PnL with +/- sign and color indicator
 */
export function formatPnL(pnl: number | null | undefined): {
  formatted: string;
  isPositive: boolean;
  colorClass: string;
} {
  if (pnl === null || pnl === undefined || isNaN(pnl)) {
    return { formatted: '$0.00', isPositive: true, colorClass: 'text-slate-400' };
  }
  const isPositive = pnl >= 0;
  const absFormatted = Math.abs(pnl).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const formatted = `${isPositive ? '+' : '-'}$${absFormatted}`;
  const colorClass = isPositive ? 'text-[#00ff88]' : 'text-[#ff3366]';

  return { formatted, isPositive, colorClass };
}

/**
 * Format UTC timestamp to "HH:MM UTC"
 */
export function formatTime(utcTimestamp: string | Date | null | undefined): string {
  if (!utcTimestamp) return '--:-- UTC';
  try {
    const date = typeof utcTimestamp === 'string' ? new Date(utcTimestamp) : utcTimestamp;
    if (isNaN(date.getTime())) return String(utcTimestamp);
    return (
      date.toLocaleTimeString('en-GB', {
        timeZone: 'UTC',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }) + ' UTC'
    );
  } catch {
    return '--:-- UTC';
  }
}

/**
 * Format currency as $X,XXX.XX
 */
export function formatCurrency(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || isNaN(amount)) return '$0.00';
  return '$' + amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * Calculate countdown and minutes until an event
 */
export function getTimeUntil(scheduledTimeStr: string | null | undefined): {
  minutesUntil: number;
  text: string;
  isWithin30m: boolean;
  isPast: boolean;
} {
  if (!scheduledTimeStr) {
    return { minutesUntil: 999, text: '--', isWithin30m: false, isPast: false };
  }
  try {
    const scheduled = new Date(scheduledTimeStr).getTime();
    const now = Date.now();
    const diffMs = scheduled - now;
    const minutesUntil = Math.round(diffMs / (60 * 1000));

    if (minutesUntil < 0) {
      return {
        minutesUntil,
        text: 'Released',
        isWithin30m: false,
        isPast: true,
      };
    }
    if (minutesUntil < 60) {
      return {
        minutesUntil,
        text: `in ${minutesUntil}m`,
        isWithin30m: minutesUntil <= 30,
        isPast: false,
      };
    }
    const hours = Math.floor(minutesUntil / 60);
    const mins = minutesUntil % 60;
    return {
      minutesUntil,
      text: `in ${hours}h ${mins}m`,
      isWithin30m: false,
      isPast: false,
    };
  } catch {
    return { minutesUntil: 999, text: '--', isWithin30m: false, isPast: false };
  }
}
