import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle2, Loader2, XCircle } from 'lucide-react';
import { quantViewApi } from '../services/api';
import { setAuthToken } from '../services/authToken';
import { useAuth } from '../contexts/AuthContext';

export const AuthCallback: React.FC = () => {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const token = params.get('token');
    if (!token) {
      setError('Missing login token. Send /login to the Telegram bot again.');
      return;
    }

    (async () => {
      try {
        let jwt = token;
        // The Telegram widget already hands us a signed JWT; the bot's magic
        // link carries a one-time code that must be exchanged first.
        if (token.split('.').length !== 3) {
          const res = await quantViewApi.verifyLogin(token);
          if (!res.data.token) {
            throw new Error('Login response did not include a session token.');
          }
          jwt = res.data.token;
        }

        setAuthToken(jwt);
        // Never leave the token in the address bar / history / referrer.
        window.history.replaceState(null, '', window.location.pathname);
        await refresh();
        navigate('/dashboard', { replace: true });
      } catch (err: any) {
        setError(err?.message || 'Login link is invalid or expired.');
      }
    })();
  }, [params, navigate, refresh]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/70 p-8 text-center">
        {error ? (
          <>
            <XCircle className="mx-auto mb-4 text-rose-400" size={40} />
            <h1 className="text-lg font-semibold text-white">Sign-in failed</h1>
            <p className="mt-2 text-sm text-slate-400">{error}</p>
            <button
              className="mt-6 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-emerald-400"
              onClick={() => navigate('/login', { replace: true })}
            >
              Back to sign in
            </button>
          </>
        ) : (
          <>
            <Loader2 className="mx-auto mb-4 animate-spin text-emerald-400" size={40} />
            <h1 className="text-lg font-semibold text-white">Verifying your login…</h1>
            <p className="mt-2 text-sm text-slate-400">This takes just a moment.</p>
            <CheckCircle2 className="mx-auto mt-4 text-slate-700" size={18} />
          </>
        )}
      </div>
    </div>
  );
};
