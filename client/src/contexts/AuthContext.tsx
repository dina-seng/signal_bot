import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { ApiError, quantViewApi, AuthUser } from '../services/api';
import { clearAuthToken, getAuthToken } from '../services/authToken';

interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isLoading: boolean;
  /** true only when an authenticated user was actually loaded. */
  refresh: () => Promise<boolean>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      // Session is a JWT in localStorage; no cookie exists to check.
      if (!getAuthToken()) {
        setUser(null);
        return false;
      }

      // Transient failures (timeout/abort, network, 502 proxy HTML during a
      // Render cold start) must NOT discard a valid token: retry 1s then 2s.
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          const res = await quantViewApi.getSession();
          if (res.data.authenticated && res.data.user) {
            setUser(res.data.user);
            return true;
          }
          // Server answered but the token is not usable.
          clearAuthToken();
          setUser(null);
          return false;
        } catch (err) {
          // 401 → token missing/invalid/expired: discard it so the route guard
          // redirects to /login.
          if (err instanceof ApiError && err.status === 401) {
            clearAuthToken();
            setUser(null);
            return false;
          }
          console.warn(
            `[Auth] Session check failed (attempt ${attempt + 1}/3): ${String(err)}` +
            (err instanceof ApiError && err.status === 502
              ? ' — 502 proxy/cold-start response, retrying with the token kept.'
              : ' — retrying with the token kept.')
          );
          if (attempt < 2) await delay(1000 * (attempt + 1));
        }
      }

      setUser(null);
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    await quantViewApi.logout();
    clearAuthToken();
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
