import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "@/i18n/I18nProvider";
import { FOCUS_RING } from "../cockpitShared";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function ConfigAnotherRunDialog({
  open,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const focusTimer = window.setTimeout(() => panelRef.current?.focus(), 0);

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const nodes = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.tabIndex !== -1,
      );
      if (nodes.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || active === panel || !panel.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !panel.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKey);
      previouslyFocused.current?.focus?.();
    };
  }, [open, onCancel]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4">
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-surface-dim/70 backdrop-blur-sm"
        onClick={onCancel}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="config-another-run-title"
        aria-describedby="config-another-run-body"
        tabIndex={-1}
        className={`glass-panel-strong relative z-10 w-full max-w-md rounded-xl shadow-2xl outline-none ${FOCUS_RING}`}
      >
        <div className="border-b border-outline/35 px-5 py-4">
          <h2
            id="config-another-run-title"
            className="font-display text-[16px] font-semibold text-text-main"
          >
            {t("cockpitSetup.run.configAnother")}
          </h2>
          <p
            id="config-another-run-body"
            className="mt-2 text-[13px] leading-relaxed text-text-variant"
          >
            {t("cockpitSetup.run.configAnotherBody")}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 px-5 py-4">
          <button
            type="button"
            onClick={onCancel}
            className={`inline-flex items-center rounded-lg border border-outline/55 px-3.5 py-2 text-[13px] font-medium text-text-dim transition hover:border-outline hover:bg-surface-low hover:text-text-main ${FOCUS_RING}`}
          >
            {t("cockpitSetup.run.configAnotherCancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 font-display text-[13px] font-semibold text-on-primary transition hover:bg-primary-dim ${FOCUS_RING}`}
          >
            {t("cockpitSetup.run.configAnotherConfirm")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
