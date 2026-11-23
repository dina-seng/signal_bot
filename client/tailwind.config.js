/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      screens: {
        xs: '480px',
      },
      colors: {
        background: '#090a0f',
        terminal: '#090a0f',
        panel: 'rgba(255, 255, 255, 0.03)',
        'panel-border': 'rgba(255, 255, 255, 0.08)',
        buy: {
          DEFAULT: '#10b981',
          glow: 'rgba(16, 185, 129, 0.15)',
          muted: 'rgba(16, 185, 129, 0.2)',
        },
        sell: {
          DEFAULT: '#f43f5e',
          glow: 'rgba(244, 63, 94, 0.15)',
          muted: 'rgba(244, 63, 94, 0.2)',
        },
      },
      fontFamily: {
        sans: ['Geist', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      backgroundImage: {
        'fintech-grid': 'linear-gradient(to right, rgba(255, 255, 255, 0.04) 1px, transparent 1px), linear-gradient(to bottom, rgba(255, 255, 255, 0.04) 1px, transparent 1px)',
        'radial-spotlight': 'radial-gradient(ellipse 65% 55% at 50% 30%, rgba(255, 255, 255, 0.08), transparent 80%)',
      },
      boxShadow: {
        'glass-sm': 'inset 0 1px 0 0 rgba(255, 255, 255, 0.08)',
        'glass-card': '0 20px 40px -15px rgba(0, 0, 0, 0.7), inset 0 1px 0 0 rgba(255, 255, 255, 0.08)',
        'glass-hover': '0 25px 50px -12px rgba(0, 0, 0, 0.8), 0 0 25px -4px rgba(16, 185, 129, 0.12), inset 0 1px 0 0 rgba(255, 255, 255, 0.15)',
        'glow-emerald': '0 0 25px rgba(16, 185, 129, 0.25)',
        'glow-rose': '0 0 25px rgba(244, 63, 94, 0.25)',
      },
      keyframes: {
        'mesh-1': {
          '0%': { transform: 'translate(0px, 0px) scale(1)' },
          '33%': { transform: 'translate(60px, -40px) scale(1.08)' },
          '66%': { transform: 'translate(-30px, 50px) scale(0.95)' },
          '100%': { transform: 'translate(0px, 0px) scale(1)' },
        },
        'mesh-2': {
          '0%': { transform: 'translate(0px, 0px) scale(1)' },
          '33%': { transform: 'translate(-50px, 35px) scale(0.94)' },
          '66%': { transform: 'translate(45px, -30px) scale(1.06)' },
          '100%': { transform: 'translate(0px, 0px) scale(1)' },
        },
        'mesh-3': {
          '0%, 100%': { transform: 'scale(1) opacity(0.5)' },
          '50%': { transform: 'scale(1.15) opacity(0.8)' },
        },
        'tick-up': {
          '0%': { textShadow: '0 0 18px rgba(16, 185, 129, 0.9)', color: '#34d399' },
          '100%': { textShadow: 'none' },
        },
        'tick-down': {
          '0%': { textShadow: '0 0 18px rgba(244, 63, 94, 0.9)', color: '#fb7185' },
          '100%': { textShadow: 'none' },
        },
      },
      animation: {
        'mesh-1': 'mesh-1 24s ease-in-out infinite alternate',
        'mesh-2': 'mesh-2 28s ease-in-out infinite alternate',
        'mesh-3': 'mesh-3 20s ease-in-out infinite alternate',
        'tick-up': 'tick-up 0.7s ease-out',
        'tick-down': 'tick-down 0.7s ease-out',
      },
    },
  },
  plugins: [],
}
