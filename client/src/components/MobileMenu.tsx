import React, { useEffect } from 'react';
import { SidebarContent, SidebarProps } from './Sidebar';

interface MobileMenuProps extends SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Mobile-only slide-in navigation drawer (< md).
 * Renders a dark, blurred backdrop and reuses the shared SidebarContent.
 * Closes on backdrop tap, Escape, or any nav item tap.
 */
export const MobileMenu: React.FC<MobileMenuProps> = ({ isOpen, onClose, ...sidebarProps }) => {
  // Escape-to-close + body scroll lock while the drawer is open.
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };

    // Close automatically if the viewport grows past the mobile breakpoint (e.g. rotate/resize),
    // so the body scroll lock never leaks into the desktop layout.
    const desktopQuery = window.matchMedia('(min-width: 768px)');
    const handleBreakpoint = (event: MediaQueryListEvent) => {
      if (event.matches) onClose();
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleKeyDown);
    desktopQuery.addEventListener('change', handleBreakpoint);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleKeyDown);
      desktopQuery.removeEventListener('change', handleBreakpoint);
    };
  }, [isOpen, onClose]);

  return (
    <div className={`md:hidden ${isOpen ? '' : 'pointer-events-none'}`}>
      {/* Backdrop — tap outside to close */}
      <div
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ${
          isOpen ? 'opacity-100' : 'opacity-0'
        }`}
        aria-hidden="true"
      />

      {/* Slide-in drawer */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Navigation menu"
        aria-hidden={!isOpen}
        inert={!isOpen}
        className={`fixed top-0 bottom-0 left-0 z-50 flex w-[240px] max-w-[85vw] flex-col bg-[#030014]/95 backdrop-blur-xl border-r border-white/10 shadow-2xl transition-transform duration-300 ease-in-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <SidebarContent {...sidebarProps} isDrawer onCloseMobile={onClose} />
      </aside>
    </div>
  );
};

export default MobileMenu;
