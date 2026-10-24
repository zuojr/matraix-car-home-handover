import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "@/i18n/I18nProvider";
import type { OverlayDimension } from "@/lib/types";
import { FOCUS_RING, Sym } from "../cockpitShared";
import {
  OVERLAY_ID_RE,
  normalizeOverlayId,
  suggestOverlayId,
} from "./personaSamplingTypes";

export interface OverlayDimensionDialogProps {
  open: boolean;
  takenIds: Set<string>;
  onClose: () => void;
  onAdd: (dimensions: OverlayDimension[]) => void;
}

type DraftDimension = {
  key: string;
  label: string;
  id: string;
  idLocked: boolean;
  values: string[];
};

let draftKeySeq = 0;

function emptyDraft(): DraftDimension {
  draftKeySeq += 1;
  return {
    key: `overlay-draft-${draftKeySeq}`,
    label: "",
    id: "",
    idLocked: false,
    values: ["", ""],
  };
}

function uniqueNonEmpty(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values) {
    const value = raw.trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

function isBlankDraft(draft: DraftDimension): boolean {
  return (
    !draft.label.trim() &&
    !draft.id.trim() &&
    uniqueNonEmpty(draft.values).length === 0
  );
}

export function OverlayDimensionDialog({
  open,
  takenIds,
  onClose,
  onAdd,
}: OverlayDimensionDialogProps) {
  const { t } = useI18n();
  const [drafts, setDrafts] = useState<DraftDimension[]>(() => [emptyDraft()]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDrafts([emptyDraft()]);
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const setDraftLabel = (key: string, next: string) => {
    setDrafts((prev) =>
      prev.map((draft) =>
        draft.key === key
          ? {
              ...draft,
              label: next,
              id: draft.idLocked ? draft.id : suggestOverlayId(next),
            }
          : draft,
      ),
    );
  };

  const setDraftId = (key: string, next: string) => {
    setDrafts((prev) =>
      prev.map((draft) =>
        draft.key === key ? { ...draft, id: next, idLocked: true } : draft,
      ),
    );
  };

  const setDraftValue = (key: string, index: number, next: string) => {
    setDrafts((prev) =>
      prev.map((draft) =>
        draft.key === key
          ? {
              ...draft,
              values: draft.values.map((value, i) => (i === index ? next : value)),
            }
          : draft,
      ),
    );
  };

  const addValueRow = (key: string) => {
    setDrafts((prev) =>
      prev.map((draft) =>
        draft.key === key ? { ...draft, values: [...draft.values, ""] } : draft,
      ),
    );
  };

  const removeValueRow = (key: string, index: number) => {
    setDrafts((prev) =>
      prev.map((draft) => {
        if (draft.key !== key || draft.values.length <= 1) return draft;
        return { ...draft, values: draft.values.filter((_, i) => i !== index) };
      }),
    );
  };

  const addDimension = () => {
    setDrafts((prev) => [...prev, emptyDraft()]);
    setError(null);
  };

  const removeDimension = (key: string) => {
    setDrafts((prev) => (prev.length <= 1 ? prev : prev.filter((draft) => draft.key !== key)));
  };

  const submit = () => {
    const filled = drafts.filter((draft) => !isBlankDraft(draft));
    if (filled.length === 0) {
      setError(t("personaSetup.filters.overlayNeedOne"));
      return;
    }
    const taken = new Set(
      [...takenIds].map((id) => normalizeOverlayId(id)).filter(Boolean),
    );
    const next: OverlayDimension[] = [];
    for (let i = 0; i < filled.length; i += 1) {
      const draft = filled[i];
      const display = draft.label.trim();
      const cleaned = uniqueNonEmpty(draft.values);
      const ordinal = drafts.findIndex((row) => row.key === draft.key) + 1;
      if (!display) {
        setError(t("personaSetup.filters.overlayNeedLabelAt", { n: ordinal }));
        return;
      }
      const id = normalizeOverlayId(draft.id);
      if (!id) {
        setError(t("personaSetup.filters.overlayNeedIdAt", { n: ordinal }));
        return;
      }
      if (!OVERLAY_ID_RE.test(id)) {
        setError(t("personaSetup.filters.overlayIdInvalidAt", { n: ordinal }));
        return;
      }
      if (taken.has(id)) {
        setError(t("personaSetup.filters.overlayIdTakenAt", { n: ordinal, id }));
        return;
      }
      if (cleaned.length === 0) {
        setError(t("personaSetup.filters.overlayNeedValuesAt", { n: ordinal }));
        return;
      }
      taken.add(id);
      next.push({ id, label: display, values: cleaned });
    }
    onAdd(next);
    onClose();
  };

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-surface-dim/70 backdrop-blur-sm"
        aria-label={t("personaSetup.common.cancel")}
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="overlay-dimension-dialog-title"
        className="glass-panel-strong relative z-10 flex max-h-[min(88vh,44rem)] w-full max-w-3xl flex-col rounded-xl shadow-2xl"
      >
        <div className="shrink-0 border-b border-outline/35 px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2
                id="overlay-dimension-dialog-title"
                className="font-display text-[16px] font-semibold text-text-main"
              >
                {t("personaSetup.filters.overlayAdd")}
              </h2>
              <p className="mt-1 text-[12px] leading-relaxed text-text-dim">
                {t("personaSetup.filters.overlayHint")}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label={t("personaSetup.common.cancel")}
              className={`shrink-0 rounded-md p-1.5 text-text-variant hover:bg-surface-high ${FOCUS_RING}`}
            >
              <Sym name="close" size={18} />
            </button>
          </div>
        </div>

        <div className="custom-scrollbar min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
          {drafts.map((draft, dimIndex) => (
            <section
              key={draft.key}
              className="rounded-xl border border-outline/35 bg-surface/25 p-3.5"
            >
              <div className="mb-2.5 flex items-center justify-between gap-2">
                <p className="text-[12px] font-medium text-text-variant">
                  {t("personaSetup.filters.overlayDimension", {
                    n: dimIndex + 1,
                  })}
                </p>
                <button
                  type="button"
                  disabled={drafts.length <= 1}
                  onClick={() => removeDimension(draft.key)}
                  aria-label={t("personaSetup.filters.overlayRemove")}
                  className={`rounded-md p-1 text-text-dim hover:bg-surface-high hover:text-danger disabled:cursor-not-allowed disabled:opacity-30 ${FOCUS_RING}`}
                >
                  <Sym name="close" size={16} />
                </button>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block min-w-0">
                  <span className="mb-1 block text-[12px] text-text-dim">
                    {t("personaSetup.filters.overlayLabel")}
                  </span>
                  <input
                    type="text"
                    value={draft.label}
                    autoFocus={dimIndex === 0}
                    onChange={(e) => setDraftLabel(draft.key, e.target.value)}
                    placeholder={t("personaSetup.filters.overlayLabelPlaceholder")}
                    className={`h-9 w-full rounded-lg border border-outline/45 bg-field px-2.5 text-[13px] text-text-main placeholder:text-text-dim ${FOCUS_RING}`}
                  />
                </label>
                <label className="block min-w-0">
                  <span className="mb-1 block text-[12px] text-text-dim">
                    {t("personaSetup.filters.overlayId")}
                  </span>
                  <input
                    type="text"
                    value={draft.id}
                    spellCheck={false}
                    autoCapitalize="none"
                    autoCorrect="off"
                    onChange={(e) => setDraftId(draft.key, e.target.value)}
                    onBlur={() => {
                      const normalized = normalizeOverlayId(draft.id);
                      if (normalized !== draft.id) setDraftId(draft.key, normalized);
                    }}
                    placeholder={t("personaSetup.filters.overlayIdPlaceholder")}
                    className={`h-9 w-full rounded-lg border border-outline/45 bg-field px-2.5 font-mono text-[13px] text-text-main placeholder:text-text-dim ${FOCUS_RING}`}
                  />
                  <span className="mt-1.5 block text-[11px] leading-relaxed text-text-dim">
                    {t("personaSetup.filters.overlayIdHint")}
                  </span>
                </label>
              </div>

              <div className="mt-3 space-y-1.5">
                <span className="block text-[12px] text-text-dim">
                  {t("personaSetup.filters.overlayValues")}
                </span>
                {draft.values.map((value, index) => (
                  <div key={`${draft.key}-v-${index}`} className="flex items-center gap-1.5">
                    <input
                      type="text"
                      value={value}
                      onChange={(e) => setDraftValue(draft.key, index, e.target.value)}
                      placeholder={t("personaSetup.filters.overlayValuePlaceholder", {
                        n: index + 1,
                      })}
                      className={`h-9 min-w-0 flex-1 rounded-lg border border-outline/45 bg-field px-2.5 text-[13px] text-text-main placeholder:text-text-dim ${FOCUS_RING}`}
                    />
                    <button
                      type="button"
                      disabled={draft.values.length <= 1}
                      onClick={() => removeValueRow(draft.key, index)}
                      aria-label={t("personaSetup.filters.overlayRemove")}
                      className={`shrink-0 rounded-md p-1.5 text-text-dim hover:bg-surface-high hover:text-danger disabled:cursor-not-allowed disabled:opacity-30 ${FOCUS_RING}`}
                    >
                      <Sym name="close" size={16} />
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => addValueRow(draft.key)}
                  className={`inline-flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-1 text-[12px] text-primary hover:bg-primary/10 ${FOCUS_RING}`}
                >
                  <Sym name="add" size={16} />
                  {t("personaSetup.filters.overlayAddValue")}
                </button>
              </div>
            </section>
          ))}

          <button
            type="button"
            onClick={addDimension}
            className={`inline-flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-1 text-[12px] font-medium text-primary hover:bg-primary/10 ${FOCUS_RING}`}
          >
            <Sym name="add" size={16} />
            {t("personaSetup.filters.overlayAddDimension")}
          </button>
        </div>

        <div className="shrink-0 border-t border-outline/35 px-5 py-3">
          {error ? <p className="mb-2 text-[12px] text-danger">{error}</p> : null}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className={`rounded-md border border-outline px-3 py-2 text-[13px] text-text-variant ${FOCUS_RING}`}
            >
              {t("personaSetup.common.cancel")}
            </button>
            <button
              type="button"
              onClick={submit}
              className={`rounded-md bg-primary px-4 py-2 text-[13px] font-medium text-on-primary ${FOCUS_RING}`}
            >
              {t("personaSetup.filters.overlayConfirm")}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
