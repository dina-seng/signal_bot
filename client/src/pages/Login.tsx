import React from 'react';
import { Link } from 'react-router-dom';
import { LockKeyhole, Send, ShieldCheck } from 'lucide-react';

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

        <ol className="space-y-4 text-sm text-slate-300">
          <li className="flex gap-3">
            <span className="font-semibold text-emerald-400">1.</span>
            <span>
              Open the QuantView bot in Telegram and send{' '}
              <code className="rounded bg-slate-800 px-1.5 py-0.5 text-emerald-300">/login</code>.
            </span>
          </li>
          <li className="flex gap-3">
            <span className="font-semibold text-emerald-400">2.</span>
            <span>Tap the <strong> Click here to log in to QuantView</strong> button.</span>
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
          <span className="inline-flex items-center gap-1 text-slate-500">
            <Send size={14} /> @signalTheBEST_bot
          </span>
        </div>
      </div>
    </div>
  );
};
