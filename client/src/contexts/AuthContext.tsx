import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { ApiError, quantViewApi, AuthUser } from '../services/api';

interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isLoading: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await quantViewApi.getSession();
      setUser(res.data.authenticated ? res.data.user : null);
    } catch (err) {
      // 401 → not logged in (expected).
      // 502 → proxy returned HTML instead of JSON (Render cold-start or broken
      //        proxy rule). Both cases: treat as logged-out, never surface a
      //        SyntaxError. Log proxy errors at warn level for visibility.
      if (err instanceof ApiError) {
        if (err.status !== 401) {
          console.warn(
            `[Auth] Session check returned HTTP ${err.status}: ${err.message}. ` +
            (err.status === 502
              ? 'Likely cause: /api/* proxy rule not matching or Render cold-start returned HTML.'
              : 'Treating as logged-out.')
          );
        }
      } else {
        // Network error, abort, etc. — still treat as logged-out.
        console.warn('[Auth] Session check failed (network/parse error):', err);
      }
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    await quantViewApi.logout();
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isAdmin: user?.is_admin === true,
      isLoading,
      refresh,
      signOut,
    }),
    [user, isLoading, refresh, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
};
