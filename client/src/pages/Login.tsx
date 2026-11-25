import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { LockKeyhole, ShieldCheck } from 'lucide-react';
import logoImg from '../../assets/logo.png';
import { TELEGRAM_WIDGET_AUTH_URL } from '../config/sameOrigin';

const botUsername = (
  import.meta.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME || 'signalTheBEST_bot'
).trim().replace(/^@/, '');

// The widget callback MUST be first-party: the session cookie is issued by the
// proxied /api path on quanview.dinacreator.space, not by the Render host.
const widgetAuthUrl = TELEGRAM_WIDGET_AUTH_URL;

export const Login: React.FC = () => {
  useEffect(() => {
    const container = document.getElementById('telegram-login-widget');
    if (!container) return;

    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://telegram.org/js/telegram-widget.js?22';
    script.setAttribute('data-telegram-login', botUsername);
    script.setAttribute('data-size', 'large');
    script.setAttribute('data-radius', '8');
    script.setAttribute('data-auth-url', widgetAuthUrl);
    script.setAttribute('data-request-access', 'write');
    container.appendChild(script);

    return () => {
      script.remove();
      container.replaceChildren();
    };
  }, [botUsername, widgetAuthUrl]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/70 p-8 shadow-2xl">
        <div className="mb-6 flex flex-col items-center text-center">
          <img
            src={logoImg}
            alt="QuantView"
            className="h-12 w-auto object-contain drop-shadow-[0_0_12px_rgba(124,58,237,0.35)]"
          />
          <h1 className="mt-4 text-xl font-semibold text-white">QuantView Sign In</h1>
          <p className="mt-1 flex items-center gap-1.5 text-sm text-slate-400">
            <LockKeyhole size={14} className="text-sky-400" />
            Secure access via Telegram
          </p>
        </div>

        <div id="telegram-login-widget" className="flex min-h-[64px] justify-center" />

        <p className="mt-3 text-center text-xs text-slate-500">
          One tap signs you in securely with @{botUsername}.
        </p>

        <div className="my-6 flex items-center gap-3 text-xs uppercase tracking-wider text-slate-600">
          <span className="h-px flex-1 bg-slate-800" />
          Manual fallback
          <span className="h-px flex-1 bg-slate-800" />
        </div>

        <ol className="space-y-4 text-sm text-slate-300">
          <li className="flex gap-3">
            <span className="font-semibold text-emerald-400">1.</span>
            <span>
              Open @{botUsername} in Telegram and send{' '}
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
          Sessions last 30 days. Login links expire after 5 minutes and are single-use.
        </div>

        <div className="mt-6 flex items-center justify-between text-sm">
          <Link to="/" className="text-slate-400 hover:text-white transition-colors">← Home</Link>
          <span className="text-slate-500">@{botUsername}</span>
        </div>
      </div>
    </div>
  );
};
