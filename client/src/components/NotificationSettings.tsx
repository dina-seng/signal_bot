import React, { useState } from 'react';
import {
  Bell,
  Send,
  Mail,
  CheckCircle,
  AlertCircle,
  ShieldCheck,
  Smartphone,
  ExternalLink,
  Radio,
  Sparkles,
  Check,
  RefreshCw,
} from 'lucide-react';
import { AlertConfiguration } from '../types';
import { BackendTelegramStatus, BackendScannerStatus, AppConfig } from '../services/api';

interface NotificationSettingsProps {
  config: AlertConfiguration;
  onUpdateConfig: (newConfig: AlertConfiguration) => void;
  onSendTestNotification: () => Promise<void>;
  isSendingTest: boolean;
  testNotificationResult: { success: boolean; message: string } | null;
  telegramStatus?: BackendTelegramStatus | null;
  scannerStatus?: BackendScannerStatus | null;
  onTriggerScanner?: () => Promise<void>;
  isTriggeringScanner?: boolean;
  appConfig?: AppConfig | null;
}

export const NotificationSettings: React.FC<NotificationSettingsProps> = ({
  config,
  onUpdateConfig,
  onSendTestNotification,
  isSendingTest,
  testNotificationResult,
  telegramStatus,
  scannerStatus,
  onTriggerScanner,
  isTriggeringScanner = false,
  appConfig,
}) => {
  const [emailInput, setEmailInput] = useState<string>(config.dailySummaryEmail);
  const [emailSaved, setEmailSaved] = useState<boolean>(false);

  const handleToggle = (key: keyof Omit<AlertConfiguration, 'dailySummaryEmail' | 'telegramBotHandle' | 'telegramChatConnected'>) => {
    onUpdateConfig({
      ...config,
      [key]: !config[key],
    });
  };

  const handleSaveEmail = (e: React.FormEvent) => {
    e.preventDefault();
    onUpdateConfig({
      ...config,
      dailySummaryEmail: emailInput.trim(),
    });
    setEmailSaved(true);
    setTimeout(() => setEmailSaved(false), 3000);
  };

  return (
    <div className="space-y-4 w-full min-w-0 font-mono">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-base font-bold text-white tracking-wide uppercase">Alert Engine & Daemon Settings</h2>
          <span className="px-1.5 py-0.5 rounded text-[9px] uppercase bg-[#161922] text-purple-300 border border-purple-500/30">
            Realtime Dispatcher
          </span>
        </div>
        <p className="text-[11px] text-slate-500 mt-0.5">
          Configure real-time automated trading alerts, risk notifications, and Telegram bot triggers
        </p>
      </div>

      {/* Main Alert Configuration Card */}
      <div className="rounded-lg p-4 bg-[#111319] border border-[#1d2230] space-y-4">
        {/* Section Title */}
        <div className="flex items-center justify-between pb-3 border-b border-[#1d2230]">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded bg-[#00e676]/10 text-[#00e676]">
              <Bell className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">Alert Configuration</h3>
              <p className="text-[10px] text-slate-500">
                Select which algorithmic events trigger instant pushes
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#0a0b10] border border-[#1d2230] text-[10px] text-slate-400">
            <span className="w-1.5 h-1.5 rounded-full bg-[#00e676]" />
            <span>Webhook: Connected</span>
          </div>
        </div>

        {/* Telegram Destination Banner (Explicitly required text) */}
        <div className="p-3 rounded bg-[#0a0b10] border border-[#1d2230] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-[#161922] border border-[#1d2230] flex items-center justify-center shrink-0">
              <Send className="w-4 h-4 text-cyan-400" />
            </div>
            <div>
              <div className="text-xs font-semibold text-white flex items-center gap-2 flex-wrap">
                <span>🔔 Alerts sent via Telegram:</span>
                <span className="text-cyan-400 font-bold bg-[#111319] px-1.5 py-0.5 rounded border border-cyan-500/30">
                  {config.telegramBotHandle}
                </span>
                {telegramStatus && (
                  <span className="px-1.5 py-0.5 rounded text-[9px] uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                    Mode: {telegramStatus.mode}
                  </span>
                )}
              </div>
              <p className="text-[10px] text-slate-500 mt-0.5">
                Target chat ID configured in backend environment with {appConfig?.duplicate_cooldown_hours ?? 2}-hour duplicate suppression
              </p>
              {telegramStatus && (
                <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-400">
                  <span>Sent: <strong className="text-white">{telegramStatus.total_messages_sent}</strong></span>
                  <span>•</span>
                  <span>Token: <strong className={telegramStatus.bot_token_present ? 'text-[#00e676]' : 'text-amber-400'}>{telegramStatus.bot_token_present ? 'Active' : 'Unset'}</strong></span>
                </div>
              )}
            </div>
          </div>

          {/* Test Notification Button */}
          <button
            onClick={onSendTestNotification}
            disabled={isSendingTest}
            className={`px-3 py-1.5 rounded text-xs font-bold flex items-center justify-center gap-1.5 transition-colors shrink-0 cursor-pointer border ${
              isSendingTest
                ? 'bg-[#161922] text-slate-500 cursor-not-allowed border-[#1d2230]'
                : 'bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300 border-cyan-500/30'
            }`}
          >
            {isSendingTest ? (
              <>
                <RefreshCw className="w-3 h-3 animate-spin text-cyan-400" />
                <span>Transmitting...</span>
              </>
            ) : (
              <>
                <Send className="w-3 h-3" />
                <span>Test Ping</span>
              </>
            )}
          </button>
        </div>

        {/* Test Notification Delivery Banner (if triggered) */}
        {testNotificationResult && (
          <div
            className={`p-2.5 rounded border text-[11px] flex items-center gap-2 ${
              testNotificationResult.success
                ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                : 'bg-[#ff3366]/10 text-[#ff3366] border-[#ff3366]/30'
            }`}
          >
            {testNotificationResult.success ? (
              <CheckCircle className="w-3.5 h-3.5 shrink-0" />
            ) : (
              <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            )}
            <span>{testNotificationResult.message}</span>
          </div>
        )}

        {/* 4 Alert Event Toggles */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
          {/* 1. New Signal Alerts */}
          <div className="p-3 rounded bg-[#0a0b10] border border-[#1d2230] flex items-start justify-between gap-3">
            <div className="space-y-0.5">
              <span className="text-xs font-semibold text-white block">
                New Signal Alerts
              </span>
              <p className="text-[10px] text-slate-500">
                Dispatches actionable alerts when confluence engine scores &ge;{' '}
                {appConfig ? (
                  `${appConfig.min_confluence_score}%`
                ) : (
                  <span className="inline-block min-w-[2rem] animate-pulse rounded bg-white/10 align-middle" aria-busy="true" aria-label="Loading score threshold" />
                )}
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={config.newSignalAlerts}
              onClick={() => handleToggle('newSignalAlerts')}
              className={`w-9 h-5 rounded-full transition-colors relative shrink-0 cursor-pointer ${
                config.newSignalAlerts ? 'bg-[#00e676]' : 'bg-[#1d2230]'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-[#0a0b10] transition-transform duration-150 ${
                  config.newSignalAlerts ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {/* 2. Position Opened/Closed */}
          <div className="p-3 rounded bg-[#0a0b10] border border-[#1d2230] flex items-start justify-between gap-3">
            <div className="space-y-0.5">
              <span className="text-xs font-semibold text-white block">
                Position Opened/Closed
              </span>
              <p className="text-[10px] text-slate-500">
                Execution notice with lot size, entry price, and slippage telemetry
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={config.positionOpenedClosed}
              onClick={() => handleToggle('positionOpenedClosed')}
              className={`w-9 h-5 rounded-full transition-colors relative shrink-0 cursor-pointer ${
                config.positionOpenedClosed ? 'bg-[#00e676]' : 'bg-[#1d2230]'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-[#0a0b10] transition-transform duration-150 ${
                  config.positionOpenedClosed ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {/* 3. Take Profit Hit */}
          <div className="p-3 rounded bg-[#0a0b10] border border-[#1d2230] flex items-start justify-between gap-3">
            <div className="space-y-0.5">
              <span className="text-xs font-semibold text-white block">
                Take Profit Hit
              </span>
              <p className="text-[10px] text-slate-500">
                Alerts when TP1 (partial scale-out) or TP2 (runner exit) is reached
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={config.takeProfitHit}
              onClick={() => handleToggle('takeProfitHit')}
              className={`w-9 h-5 rounded-full transition-colors relative shrink-0 cursor-pointer ${
                config.takeProfitHit ? 'bg-[#00e676]' : 'bg-[#1d2230]'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-[#0a0b10] transition-transform duration-150 ${
                  config.takeProfitHit ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {/* 4. Stop Loss Hit */}
          <div className="p-3 rounded bg-[#0a0b10] border border-[#1d2230] flex items-start justify-between gap-3">
            <div className="space-y-0.5">
              <span className="text-xs font-semibold text-white block">
                Stop Loss Hit
              </span>
              <p className="text-[10px] text-slate-500">
                Capital preservation trigger alert on predetermined invalidation
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={config.stopLossHit}
              onClick={() => handleToggle('stopLossHit')}
              className={`w-9 h-5 rounded-full transition-colors relative shrink-0 cursor-pointer ${
                config.stopLossHit ? 'bg-[#00e676]' : 'bg-[#1d2230]'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-[#0a0b10] transition-transform duration-150 ${
                  config.stopLossHit ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
          </div>
        </div>

        {/* Email Input Field for Daily Summaries */}
        <div className="pt-3 border-t border-[#1d2230] space-y-2">
          <div>
            <label
              htmlFor="summaryEmail"
              className="text-xs font-semibold text-white flex items-center gap-1.5"
            >
              <Mail className="w-3.5 h-3.5 text-cyan-400" />
              Daily Summary Email (Optional)
            </label>
            <p className="text-[10px] text-slate-500">
              Receive end-of-day P&L recaps, equity curve updates, and tomorrow's high-impact news preview
            </p>
          </div>

          <form onSubmit={handleSaveEmail} className="flex gap-2">
            <div className="relative flex-1">
              <input
                id="summaryEmail"
                type="email"
                placeholder="trader@quantdesk.com"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
                className="w-full px-3 py-1.5 rounded bg-[#0a0b10] border border-[#1d2230] text-slate-200 text-xs placeholder:text-slate-600 focus:outline-none focus:border-[#00e676]/60 transition-colors"
              />
            </div>
            <button
              type="submit"
              className="px-3 py-1.5 rounded bg-[#161922] hover:bg-[#1d212d] text-slate-200 hover:text-white border border-[#1d2230] text-xs font-semibold transition-colors flex items-center gap-1.5 shrink-0 cursor-pointer"
            >
              {emailSaved ? (
                <>
                  <Check className="w-3 h-3 text-[#00e676]" />
                  <span className="text-[#00e676]">Saved</span>
                </>
              ) : (
                <span>Save</span>
              )}
            </button>
          </form>
        </div>
      </div>

      {/* Automated Background Scanner Card */}
      <div className="rounded-lg p-4 bg-[#111319] border border-[#1d2230] space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-[#1d2230]">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded bg-cyan-500/10 text-cyan-400">
              <Radio className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">Automated Background Market Scanner</h3>
              <p className="text-[10px] text-slate-500">
                Continuous daemon scanning 1h / 15m SMC confluence across major pairs
              </p>
            </div>
          </div>

          <span
            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${
              scannerStatus?.is_running
                ? 'bg-[#00e676]/10 text-[#00e676] border-[#00e676]/30'
                : 'bg-[#161922] text-slate-400 border-[#1d2230]'
            }`}
          >
            {scannerStatus?.is_running ? '● DAEMON ACTIVE' : '○ STANDBY'}
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          <div className="p-2.5 rounded bg-[#0a0b10] border border-[#1d2230]">
            <span className="text-[9px] text-slate-500 uppercase block">Interval</span>
            <span className="font-bold text-slate-200">
              {scannerStatus?.interval_minutes || 60} Minutes
            </span>
          </div>

          <div className="p-2.5 rounded bg-[#0a0b10] border border-[#1d2230]">
            <span className="text-[9px] text-slate-500 uppercase block">Auto-Paper Trade</span>
            <span className="font-bold text-[#00e676]">
              {scannerStatus?.auto_paper_trade ? 'ENABLED' : 'DISABLED'}
            </span>
          </div>

          <div className="p-2.5 rounded bg-[#0a0b10] border border-[#1d2230]">
            <span className="text-[9px] text-slate-500 uppercase block">Total Cycles</span>
            <span className="font-bold text-cyan-400">
              {scannerStatus?.total_scans_completed || 0} Runs
            </span>
          </div>

          <div className="p-2.5 rounded bg-[#0a0b10] border border-[#1d2230]">
            <span className="text-[9px] text-slate-500 uppercase block">Next Scan In</span>
            <span className="font-bold text-amber-400">
              {scannerStatus?.next_scan_at
                ? new Date(scannerStatus.next_scan_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' UTC'
                : 'Scheduled'}
            </span>
          </div>
        </div>

        {onTriggerScanner && (
          <div className="pt-1 flex justify-end">
            <button
              onClick={onTriggerScanner}
              disabled={isTriggeringScanner}
              className={`min-h-[44px] sm:min-h-0 px-3.5 py-1.5 rounded-xl text-xs font-semibold font-sans flex items-center gap-2 transition-all duration-300 cursor-pointer border ${
                isTriggeringScanner
                  ? 'bg-zinc-800 text-zinc-500 cursor-not-allowed border-white/10'
                  : 'bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white border-violet-400/30 shadow-[0_0_15px_rgba(124,58,237,0.35)] hover:shadow-[0_0_20px_rgba(124,58,237,0.55)]'
              }`}
            >
              {isTriggeringScanner ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-white" />
                  <span>Triggering Cycle...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5 text-white" />
                  <span>Trigger Scanner Now</span>
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
