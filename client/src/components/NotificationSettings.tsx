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

interface NotificationSettingsProps {
  config: AlertConfiguration;
  onUpdateConfig: (newConfig: AlertConfiguration) => void;
  onSendTestNotification: () => Promise<void>;
  isSendingTest: boolean;
  testNotificationResult: { success: boolean; message: string } | null;
}

export const NotificationSettings: React.FC<NotificationSettingsProps> = ({
  config,
  onUpdateConfig,
  onSendTestNotification,
  isSendingTest,
  testNotificationResult,
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
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-bold text-white tracking-tight">Notification Settings</h2>
          <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-purple-500/15 text-purple-300 border border-purple-500/30">
            Realtime Dispatcher
          </span>
        </div>
        <p className="text-xs text-slate-400 font-mono mt-1">
          Configure real-time automated trading alerts, risk notifications, and Telegram bot triggers
        </p>
      </div>

      {/* Main Alert Configuration Card */}
      <div className="rounded-xl p-6 bg-[#12121a] border border-[#1e1e2d] shadow-terminal space-y-6">
        {/* Section Title */}
        <div className="flex items-center justify-between pb-4 border-b border-[#1e1e2d]">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-[#00ff88]/10 text-[#00ff88]">
              <Bell className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Alert Configuration</h3>
              <p className="text-xs text-slate-400">
                Choose which algorithmic events trigger instant pushes
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-[#181824] border border-[#1e1e2d] text-xs font-mono text-slate-300">
            <span className="w-2 h-2 rounded-full bg-[#00ff88] animate-pulse" />
            <span>Webhook: Connected</span>
          </div>
        </div>

        {/* Telegram Destination Banner (Explicitly required text) */}
        <div className="p-4 rounded-xl bg-gradient-to-r from-[#181828] via-[#151522] to-[#181828] border border-cyan-500/30 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center shrink-0">
              <Send className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <div className="text-sm font-semibold text-white flex items-center gap-2">
                <span>🔔 Alerts sent via Telegram:</span>
                <span className="font-mono text-cyan-400 font-bold bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-500/40">
                  {config.telegramBotHandle}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Target chat ID configured in backend environment with 2-hour duplicate suppression
              </p>
            </div>
          </div>

          {/* Test Notification Button */}
          <button
            onClick={onSendTestNotification}
            disabled={isSendingTest}
            className={`px-4 py-2.5 rounded-lg text-xs font-mono font-bold flex items-center justify-center gap-2 transition-all shrink-0 cursor-pointer ${
              isSendingTest
                ? 'bg-[#1e1e2d] text-slate-400 cursor-not-allowed'
                : 'bg-gradient-to-r from-cyan-600 to-emerald-600 hover:from-cyan-500 hover:to-emerald-500 text-white shadow-[0_0_15px_rgba(6,182,212,0.3)] hover:shadow-[0_0_20px_rgba(0,255,136,0.4)]'
            }`}
          >
            {isSendingTest ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin text-cyan-400" />
                <span>Sending Telegram Ping...</span>
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                <span>Test Notification</span>
              </>
            )}
          </button>
        </div>

        {/* Test Notification Delivery Banner (if triggered) */}
        {testNotificationResult && (
          <div
            className={`p-3 rounded-lg border text-xs font-mono flex items-center gap-2.5 animate-fadeIn ${
              testNotificationResult.success
                ? 'bg-[#00ff88]/10 text-[#00ff88] border-[#00ff88]/30'
                : 'bg-[#ff3366]/10 text-[#ff3366] border-[#ff3366]/30'
            }`}
          >
            {testNotificationResult.success ? (
              <CheckCircle className="w-4 h-4 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 shrink-0" />
            )}
            <span>{testNotificationResult.message}</span>
          </div>
        )}

        {/* 4 Alert Event Toggles */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
          {/* 1. New Signal Alerts */}
          <div className="p-4 rounded-xl bg-[#0a0a0f] border border-[#1e1e2d] flex items-start justify-between gap-4">
            <div className="space-y-1">
              <span className="text-sm font-semibold text-white block">
                New Signal Alerts
              </span>
              <p className="text-xs text-slate-400">
                Dispatches actionable alerts whenever confluence engine scores a setup &ge; 75%
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={config.newSignalAlerts}
              onClick={() => handleToggle('newSignalAlerts')}
              className={`w-12 h-6 rounded-full transition-colors relative shrink-0 cursor-pointer ${
                config.newSignalAlerts ? 'bg-[#00ff88]' : 'bg-[#1e1e2d]'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-[#0a0a0f] transition-transform duration-200 shadow-md ${
                  config.newSignalAlerts ? 'translate-x-6' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {/* 2. Position Opened/Closed */}
          <div className="p-4 rounded-xl bg-[#0a0a0f] border border-[#1e1e2d] flex items-start justify-between gap-4">
            <div className="space-y-1">
              <span className="text-sm font-semibold text-white block">
                Position Opened/Closed
              </span>
              <p className="text-xs text-slate-400">
                Instant execution notice with lot size, entry price, and slippage telemetry
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={config.positionOpenedClosed}
              onClick={() => handleToggle('positionOpenedClosed')}
              className={`w-12 h-6 rounded-full transition-colors relative shrink-0 cursor-pointer ${
                config.positionOpenedClosed ? 'bg-[#00ff88]' : 'bg-[#1e1e2d]'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-[#0a0a0f] transition-transform duration-200 shadow-md ${
                  config.positionOpenedClosed ? 'translate-x-6' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {/* 3. Take Profit Hit */}
          <div className="p-4 rounded-xl bg-[#0a0a0f] border border-[#1e1e2d] flex items-start justify-between gap-4">
            <div className="space-y-1">
              <span className="text-sm font-semibold text-white block">
                Take Profit Hit
              </span>
              <p className="text-xs text-slate-400">
                Alerts when TP1 (partial 50% scale-out) or TP2 (full runner exit) is reached
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={config.takeProfitHit}
              onClick={() => handleToggle('takeProfitHit')}
              className={`w-12 h-6 rounded-full transition-colors relative shrink-0 cursor-pointer ${
                config.takeProfitHit ? 'bg-[#00ff88]' : 'bg-[#1e1e2d]'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-[#0a0a0f] transition-transform duration-200 shadow-md ${
                  config.takeProfitHit ? 'translate-x-6' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {/* 4. Stop Loss Hit */}
          <div className="p-4 rounded-xl bg-[#0a0a0f] border border-[#1e1e2d] flex items-start justify-between gap-4">
            <div className="space-y-1">
              <span className="text-sm font-semibold text-white block">
                Stop Loss Hit
              </span>
              <p className="text-xs text-slate-400">
                Capital preservation trigger alert if price reaches predetermined invalidation
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={config.stopLossHit}
              onClick={() => handleToggle('stopLossHit')}
              className={`w-12 h-6 rounded-full transition-colors relative shrink-0 cursor-pointer ${
                config.stopLossHit ? 'bg-[#00ff88]' : 'bg-[#1e1e2d]'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-[#0a0a0f] transition-transform duration-200 shadow-md ${
                  config.stopLossHit ? 'translate-x-6' : 'translate-x-0'
                }`}
              />
            </button>
          </div>
        </div>

        {/* Email Input Field for Daily Summaries */}
        <div className="pt-4 border-t border-[#1e1e2d] space-y-3">
          <div>
            <label
              htmlFor="summaryEmail"
              className="text-sm font-semibold text-white flex items-center gap-2"
            >
              <Mail className="w-4 h-4 text-cyan-400" />
              Daily Summary Email (Optional)
            </label>
            <p className="text-xs text-slate-400 mt-0.5">
              Receive automated end-of-day P&L recaps, equity curve updates, and tomorrow's high-impact news preview
            </p>
          </div>

          <form onSubmit={handleSaveEmail} className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <input
                id="summaryEmail"
                type="email"
                placeholder="your.desk@fund.com"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
                className="w-full px-4 py-2.5 rounded-lg bg-[#0a0a0f] border border-[#1e1e2d] text-slate-200 text-xs font-mono placeholder:text-slate-600 focus:outline-none focus:border-[#00ff88]/60 transition-colors"
              />
            </div>
            <button
              type="submit"
              className="px-5 py-2.5 rounded-lg bg-[#181824] hover:bg-[#202030] text-slate-200 hover:text-white border border-[#1e1e2d] hover:border-[#2a2a3e] text-xs font-mono font-bold transition-all flex items-center justify-center gap-2 shrink-0 cursor-pointer"
            >
              {emailSaved ? (
                <>
                  <Check className="w-3.5 h-3.5 text-[#00ff88]" />
                  <span className="text-[#00ff88]">Saved</span>
                </>
              ) : (
                <span>Save Email</span>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
