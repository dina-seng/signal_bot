import React, { useEffect } from 'react';
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react';

export interface ToastMessage {
  id: string;
  type: 'success' | 'warning' | 'info';
  title: string;
  message: string;
}

interface ToastProps {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
}

export const ToastContainer: React.FC<ToastProps> = ({ toasts, onDismiss }) => {
  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 max-w-md w-full pointer-events-none">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
};

const ToastItem: React.FC<{ toast: ToastMessage; onDismiss: (id: string) => void }> = ({
  toast,
  onDismiss,
}) => {
  useEffect(() => {
    const timer = setTimeout(() => {
      onDismiss(toast.id);
    }, 4500);
    return () => clearTimeout(timer);
  }, [toast.id, onDismiss]);

  const borderClass =
    toast.type === 'success'
      ? 'border-[#00e676]/40 bg-[#111319]/95 text-slate-100'
      : toast.type === 'warning'
      ? 'border-[#ff3366]/40 bg-[#111319]/95 text-slate-100'
      : 'border-cyan-500/40 bg-[#111319]/95 text-slate-100';

  const icon =
    toast.type === 'success' ? (
      <CheckCircle2 className="w-4 h-4 text-[#00e676] shrink-0" />
    ) : toast.type === 'warning' ? (
      <AlertTriangle className="w-4 h-4 text-[#ff3366] shrink-0" />
    ) : (
      <Info className="w-4 h-4 text-cyan-400 shrink-0" />
    );

  return (
    <div
      className={`pointer-events-auto flex items-start gap-3 p-3 rounded-md border ${borderClass} backdrop-blur-md transition-all duration-200 shadow-terminal`}
    >
      <div className="mt-0.5">{icon}</div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-bold uppercase tracking-wider font-mono text-slate-300">
          {toast.title}
        </p>
        <p className="text-sm text-slate-200 mt-0.5 break-words">{toast.message}</p>
      </div>
      <button
        onClick={() => onDismiss(toast.id)}
        className="text-slate-400 hover:text-slate-100 transition-colors p-1"
        aria-label="Close toast"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
};
