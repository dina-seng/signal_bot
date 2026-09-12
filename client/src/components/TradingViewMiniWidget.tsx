import React, { useEffect, useRef } from 'react';

export const TRADINGVIEW_SYMBOLS: Record<string, string> = {
  'XAU/USD': 'TVC:GOLD',
  'USD/JPY': 'FX:USDJPY',
};

interface TradingViewMiniWidgetProps {
  symbol: string;
  height?: number | string;
  width?: number | string;
}

export const TradingViewMiniWidget: React.FC<TradingViewMiniWidgetProps> = ({
  symbol,
  height = 190,
  width = '100%',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const tvSymbol = TRADINGVIEW_SYMBOLS[symbol] || symbol;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Reset container DOM to prevent duplicate widgets on re-mount or symbol changes
    container.innerHTML = '';

    const widgetDiv = document.createElement('div');
    widgetDiv.className = 'tradingview-widget-container__widget';
    widgetDiv.style.width = '100%';
    widgetDiv.style.height = '100%';
    container.appendChild(widgetDiv);

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js';
    script.type = 'text/javascript';
    script.async = true;
    script.innerHTML = JSON.stringify({
      symbol: tvSymbol,
      width: '100%',
      height: '100%',
      locale: 'en',
      dateRange: '1D',
      colorTheme: 'dark',
      isTransparent: true,
      autosize: true,
      largeChartUrl: '',
    });

    container.appendChild(script);

    return () => {
      if (container) {
        container.innerHTML = '';
      }
    };
  }, [tvSymbol]);

  return (
    <div
      className="tradingview-widget-container relative w-full rounded-md border border-[#1d2230] bg-[#12121a]/80 overflow-hidden"
      style={{ height, width }}
      ref={containerRef}
    >
      <div className="tradingview-widget-container__widget" style={{ height: '100%', width: '100%' }} />
    </div>
  );
};
