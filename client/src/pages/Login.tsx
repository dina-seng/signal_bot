import React from 'react';
import { Link } from 'react-router-dom';
import { LockKeyhole, ShieldCheck } from 'lucide-react';

const configuredBot = (
  import.meta.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME || 'signalTheBEST_bot'
).trim().replace(/^@/, '');

const telegramLoginUrl = `https://t.me/${configuredBot}?start=login`;

const TelegramIcon: React.FC<{ size?: number }> = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M21.7 3.5 18.3 17.3c-.25 1.02-.92 1.27-1.87.79l-4.6-3.39-2.22 2.14c-.25.25-.46.46-.94.46l.34-4.9 8.9-8.05c.39-.34-.08-.53-.6-.2L7.2 12.8l-4.36-1.36c-.95-.3-.97-.95.2-1.4L19.95 2.6c.81-.3 1.51.2 1.75.9z" />
  </svg>
);

export const Login: React.FC = () => {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/70 p-8 shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <span className="p-3 rounded-xl bg-emerald-500/10 text-emerald-400">
            <LockKeyhole size={22} />
          </span>
          <div>
            <h1 className="text-xl font-semibold text-white">QuantView Sign In</h1>
            <p className="text-sm text-slate-400">Telegram-only authentication</p>
          </div>
        </div>

        <a
          href={telegramLoginUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex w-full items-center justify-center gap-3 rounded-xl bg-sky-500 px-5 py-4 text-base font-semibold text-white shadow-lg shadow-sky-500/20 transition hover:-translate-y-0.5 hover:bg-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-300"
        >
          <TelegramIcon size={22} />
          Login with Telegram
        </a>

        <p className="mt-3 text-center text-xs text-slate-500">
          Opens @{configuredBot} and starts the secure sign-in automatically.
        </p>

        <div className="my-6 flex items-center gap-3 text-xs uppercase tracking-wider text-slate-600">
          <span className="h-px flex-1 bg-slate-800" />
          Manual steps
          <span className="h-px flex-1 bg-slate-800" />
        </div>

        <ol className="space-y-4 text-sm text-slate-300">
          <li className="flex gap-3">
            <span className="font-semibold text-emerald-400">1.</span>
            <span>
              Open @{configuredBot} in Telegram and send{' '}
              <code className="rounded bg-slate-800 px-1.5 py-0.5 text-emerald-300">/login</code>
              {' '}(or{' '}
              <code className="rounded bg-slate-800 px-1.5 py-0.5 text-emerald-300">/start login</code>
              ).
            </span>
          </li>
          <li className="flex gap-3">
            <span className="font-semibold text-emerald-400">2.</span>
            <span>Tap the <strong>🔐 Click here to log in to QuantView</strong> button.</span>
          </li>
          <li className="flex gap-3">
            <span className="font-semibold text-emerald-400">3.</span>
            <span>You will be redirected here with an active session.</span>
          </li>
        </ol>

        <div className="mt-6 flex items-center gap-2 rounded-lg bg-emerald-500/5 p-3 text-xs text-emerald-300">
          <ShieldCheck size={16} />
          Login links expire after 5 minutes and can only be used once.
        </div>

        <div className="mt-6 flex items-center justify-between text-sm">
          <Link to="/" className="text-slate-400 hover:text-white transition-colors">← Home</Link>
          <span className="text-slate-500">@{configuredBot}</span>
        </div>
      </div>
    </div>
  );
};
