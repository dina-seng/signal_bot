/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: '#0a0b10',
        terminal: '#0a0b10',
        panel: '#111319',
        'panel-subtle': '#0e1015',
        'panel-light': '#161922',
        'panel-elevated': '#1d212d',
        'panel-border': '#1d2230',
        'panel-border-subtle': '#151824',
        'panel-border-strong': '#282f42',
        buy: {
          DEFAULT: '#00e676',
          glow: 'rgba(0, 230, 118, 0.12)',
          muted: 'rgba(0, 230, 118, 0.18)',
        },
        sell: {
          DEFAULT: '#ff3366',
          glow: 'rgba(255, 51, 102, 0.12)',
          muted: 'rgba(255, 51, 102, 0.18)',
        },
        bull: {
          DEFAULT: '#00e676',
          subtle: 'rgba(0, 230, 118, 0.10)',
          border: 'rgba(0, 230, 118, 0.25)',
        },
        bear: {
          DEFAULT: '#ff3366',
          subtle: 'rgba(255, 51, 102, 0.10)',
          border: 'rgba(255, 51, 102, 0.25)',
        },
        accent: {
          cyan: '#00d2ff',
          amber: '#ffb800',
          purple: '#9d4edd',
          slate: '#64748b',
        },
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      boxShadow: {
        'terminal': '0 2px 8px -1px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.04)',
        'terminal-elevated': '0 8px 24px -4px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.07)',
        'buy-glow': '0 0 12px rgba(0, 230, 118, 0.15)',
        'sell-glow': '0 0 12px rgba(255, 51, 102, 0.15)',
      },
    },
  },
  plugins: [],
}
