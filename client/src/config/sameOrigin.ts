/**
 * Browser-facing URLs must stay on the frontend origin.
 *
 * Netlify proxies /api/* to the Render backend, and Vite does the same in dev.
 * Never point the widget callback or API calls directly at onrender.com: that
 * turns the session cookie into a third-party cookie, which mobile Safari/Chrome
 * drop on the auth redirect (ITP/STP) and causes a /login loop.
 */
export const SITE_ORIGIN = 'https://quanview.dinacreator.space';
export const API_BASE_PATH = '/api/v1';

/** Absolute same-origin callback required by the Telegram Login Widget. */
export const TELEGRAM_WIDGET_AUTH_URL = `${SITE_ORIGIN}${API_BASE_PATH}/auth/telegram-widget-verify`;
