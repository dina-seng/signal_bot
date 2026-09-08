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
        background: '#0a0a0f',
        panel: '#12121a',
        'panel-light': '#181824',
        'panel-border': '#1e1e2d',
        'panel-border-subtle': '#161622',
        buy: {
          DEFAULT: '#00ff88',
          glow: 'rgba(0, 255, 136, 0.15)',
          muted: 'rgba(0, 255, 136, 0.25)',
        },
        sell: {
          DEFAULT: '#ff3366',
          glow: 'rgba(255, 51, 102, 0.15)',
          muted: 'rgba(255, 51, 102, 0.25)',
        },
        accent: {
          cyan: '#00d2ff',
          amber: '#ffb800',
          purple: '#9d4edd',
        },
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      boxShadow: {
        'terminal': '0 4px 20px -2px rgba(0, 0, 0, 0.7), 0 0 1px 1px rgba(255, 255, 255, 0.05)',
        'buy-glow': '0 0 15px rgba(0, 255, 136, 0.25)',
        'sell-glow': '0 0 15px rgba(255, 51, 102, 0.25)',
      },
    },
  },
  plugins: [],
}
