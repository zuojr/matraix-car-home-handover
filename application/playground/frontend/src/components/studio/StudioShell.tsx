import type { ReactNode } from "react";

import { FOCUS_RING, Sym } from "../cockpit/cockpitShared";

/** Cockpit-style mesh background wrapper for Home, Runs, Persona World, etc. */
export function StudioMeshShell({ children }: { children: ReactNode }) {
  return (
    <div className="cockpit-mesh-bg flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
  );
}

export interface StudioPageHeaderProps {
  /** Deprecated — no longer rendered; the top nav already gives context. */
  eyebrow?: string;
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
  /** Deprecated — the header is always dense now. */
  compact?: boolean;
}

/** Dense one-line page header: title · subtitle inline, meta/actions right. */
export function StudioPageHeader({ title, subtitle, actions, meta }: StudioPageHeaderProps) {
  return (
    <div className="mb-3.5 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5">
      <h1 className="shrink-0 font-display text-[19px] font-bold leading-tight tracking-tight text-text-main">
        {title}
      </h1>
      {subtitle && (
        <div className="min-w-0 flex-1 basis-64 text-[13.5px] leading-snug text-text-variant">
          {subtitle}
        </div>
      )}
      {meta}
      {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StudioGlassPanel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  // Callers may pass overflow-visible for dropdowns; don't force overflow-hidden
  // ahead of that or Tailwind's conflicting-utility order can clip menus.
  const overflowClass = /\boverflow-/.test(className) ? "" : "overflow-hidden";
  return (
    <div className={`glass-panel rounded-xl ${overflowClass} ${className}`.trim()}>
      {children}
    </div>
  );
}

export function StudioPageFrame({
  children,
  fill,
}: {
  children: ReactNode;
  /** Lock the frame to the viewport and let children fill (no page scrollbar). */
  fill?: boolean;
}) {
  return (
    <div
      className={`custom-scrollbar min-h-0 flex-1 ${
        fill ? "flex flex-col overflow-hidden" : "overflow-auto"
      }`}
    >
      <div
        className={`mx-auto w-full max-w-[1180px] px-5 py-4 xl:px-6 xl:py-5 ${
          fill ? "flex min-h-0 flex-1 flex-col" : ""
        }`}
      >
        {children}
      </div>
    </div>
  );
}

export function StudioToolbarButton({
  children,
  onClick,
  disabled,
  icon,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  icon?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`glass-tile glass-tile--hover flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] text-text-variant backdrop-blur transition ease-out hover:text-text-main active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-55 ${FOCUS_RING}`}
    >
      {icon && <Sym name={icon} size={16} className={disabled ? "" : ""} />}
      {children}
    </button>
  );
}
