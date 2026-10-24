import type { ReactNode } from "react";

import { useI18n } from "@/i18n/I18nProvider";
import { ApiError } from "@/lib/api";
import type {
  ExperimentAxis,
  ExperimentDesignType,
  ExperimentMetricContract,
} from "@/lib/types";
import { Sym, humanizeToken } from "../cockpit/cockpitShared";

/**
 * Canonical section header for every experiment panel. Matches the app's
 * `CockpitRailHeader` language (primary accent bar + display title) so the
 * whole surface reads as one UI, with room for an icon, hint, and right slot.
 */
export function SectionHeader({
  title,
  hint,
  icon,
  right,
}: {
  title: string;
  hint?: ReactNode;
  icon?: string;
  right?: ReactNode;
}) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <span className="h-4 w-0.5 shrink-0 rounded-full bg-primary" aria-hidden />
      {icon ? <Sym name={icon} size={16} className="text-primary" /> : null}
      <h3 className="font-display text-[14.5px] font-semibold leading-none tracking-tight text-text-main">
        {title}
      </h3>
      {hint ? <span className="text-[11.5px] text-text-dim">· {hint}</span> : null}
      {right ? <div className="ml-auto flex items-center gap-1.5">{right}</div> : null}
    </div>
  );
}

export type ChipTone = "neutral" | "primary" | "secondary" | "warn" | "danger";

const CHIP_TONE: Record<ChipTone, string> = {
  neutral: "bg-surface-high/60 text-text-variant",
  primary: "bg-primary/12 text-primary",
  secondary: "bg-secondary/12 text-secondary",
  warn: "bg-warn/12 text-warn",
  danger: "bg-danger/12 text-danger",
};

/** Small meta chip shared across experiment panels (matches app chip tones). */
export function MetaChip({
  children,
  tone = "neutral",
  mono,
  className = "",
}: {
  children: ReactNode;
  tone?: ChipTone;
  mono?: boolean;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11.5px] font-medium ${CHIP_TONE[tone]} ${
        mono ? "font-mono" : ""
      } ${className}`.trim()}
    >
      {children}
    </span>
  );
}

/** Border card matching the Task Gallery / Persona World card language. */
export const CARD_CLASS =
  "rounded-xl border border-outline/40 bg-surface/30 transition";

/** Primary launch CTA, matching the cockpit RunLaunchBar. */
export const LAUNCH_CTA_CLASS =
  "glow inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-6 py-3 font-display text-[15px] font-bold text-on-primary transition hover:bg-primary-dim active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50";

export const DESIGNS: [ExperimentDesignType, string, string][] = [
  ["ab_n", "A/B/n", "Vary one factor at a time (OFAT)"],
  ["full_factorial", "Full factorial", "All combinations + interactions"],
  ["fractional", "Fractional", "Orthogonal array, fewer arms"],
];

const DESIGN_LABELS: Record<string, string> = {
  ab_n: "A/B/n",
  full_factorial: "Full factorial",
  fractional: "Fractional",
  put: "Persona contrast",
};

type TFn = ReturnType<typeof useI18n>["t"];

export function designLabel(type: string | undefined, t?: TFn): string {
  if (!type) return "—";
  if (t) {
    if (type === "ab_n") return t("experiments.list.filter.design.abN");
    if (type === "full_factorial") return t("experiments.list.filter.design.factorial");
    if (type === "fractional") return t("experiments.list.filter.design.fractional");
    if (type === "put") return t("catalog.taskGallery.design.personaContrast");
  }
  return DESIGN_LABELS[type] ?? type.replace(/_/g, " ");
}

export const DEFAULT_EXPERIMENT_TASK = "experiments/tasks/web-compare-options";

export function AxisBadge({ axis }: { axis: ExperimentAxis | string }) {
  const { t } = useI18n();
  const isPut = axis === "put";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ${
        isPut ? "bg-secondary/12 text-secondary" : "bg-primary/12 text-primary"
      }`}
      title={
        isPut
          ? t("experiments.shared.axisBadge.putTooltip")
          : t("experiments.shared.axisBadge.sutTooltip")
      }
    >
      {isPut ? "PUT" : "SUT"}
    </span>
  );
}

export const AXIS_META: Record<
  ExperimentAxis,
  { code: string; title: string; blurb: string; icon: string }
> = {
  sut: {
    code: "SUT",
    title: "System under test",
    blurb: "Same cohort across environment arms (paired).",
    icon: "science",
  },
  put: {
    code: "PUT",
    title: "Persona under test",
    blurb: "Fixed environment; arms differ by persona attribute.",
    icon: "groups",
  },
};

export function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Request failed";
}

const STATUS_META: Record<string, { cls: string; icon: string; label: string; spin?: boolean }> = {
  complete: { cls: "bg-secondary/12 text-secondary", icon: "check_circle", label: "complete" },
  partial: { cls: "bg-warn/12 text-warn", icon: "check_circle", label: "partial" },
  running: { cls: "bg-primary/12 text-primary", icon: "autorenew", label: "running", spin: true },
  launching: { cls: "bg-primary/12 text-primary", icon: "autorenew", label: "launching", spin: true },
  pending: { cls: "bg-surface-high/60 text-text-dim", icon: "schedule", label: "pending" },
  failed: { cls: "bg-danger/12 text-danger", icon: "error", label: "failed" },
  error: { cls: "bg-danger/12 text-danger", icon: "error", label: "error" },
};

export function StatusChip({ status }: { status?: string }) {
  const { t } = useI18n();
  const s = (status ?? "").toLowerCase();
  const meta = STATUS_META[s];
  if (!meta) {
    return (
      <span className="rounded-full bg-surface-high/60 px-2 py-0.5 text-[11px] font-semibold text-text-dim">
        {status || "—"}
      </span>
    );
  }
  const statusLabels: Record<string, string> = {
    complete: t("experiments.shared.status.complete"),
    partial: t("experiments.shared.status.partial"),
    running: t("experiments.shared.status.running"),
    launching: t("experiments.shared.status.launching"),
    pending: t("experiments.shared.status.pending"),
    failed: t("experiments.shared.status.failed"),
    error: t("experiments.shared.status.error"),
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${meta.cls}`}
    >
      <Sym name={meta.icon} size={12} className={meta.spin ? "animate-rb-spin" : ""} />
      {statusLabels[s] ?? meta.label}
    </span>
  );
}

/** Last path segment of a persona pool id, for compact tables. */
export function poolSlug(pool?: string | null): string {
  if (!pool) return "—";
  const slug = pool.split("/").filter(Boolean).pop();
  return slug || pool;
}

export interface ArmCohortRow {
  arm: string;
  group: string;
  n: number | null;
  pool?: string | null;
  reference?: boolean;
  /** Per-arm failure (e.g. the tested value can't pass the persona DAG). */
  error?: string | null;
  /** This arm is still being synthesized (live streaming). */
  pending?: boolean;
}

/** Arm (what we test) ↔ cohort slice (who we generated or drew). */
export function ArmCohortMap({
  rows,
  hint,
  emptyLabel = "not drawn yet",
}: {
  rows: ArmCohortRow[];
  hint?: string;
  /** Cohort-cell text before a slice exists (e.g. "not synthesized yet"). */
  emptyLabel?: string;
}) {
  const { t } = useI18n();
  if (rows.length === 0) return null;
  const pools = [
    ...new Set(rows.map((r) => r.pool).filter((p): p is string => Boolean(p))),
  ];
  const sharedPool = pools.length === 1 ? pools[0] : null;
  return (
    <div className="overflow-hidden rounded-lg border border-outline/30 bg-surface/40">
      {hint || sharedPool ? (
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-outline/20 px-3 py-1.5">
          {hint ? <p className="text-[11.5px] text-text-dim">{hint}</p> : <span />}
          {sharedPool ? (
            <p className="font-mono text-[11px] text-text-dim" title={sharedPool}>
              {poolSlug(sharedPool)}
            </p>
          ) : null}
        </div>
      ) : null}
      <table className="w-full text-[12px]">
        <thead>
          <tr className="border-b border-outline/20 text-left text-[10.5px] uppercase tracking-wide text-text-dim">
            <th className="px-3 py-1.5 font-medium">{t("experiments.shared.armCohort.arm")}</th>
            <th className="px-3 py-1.5 font-medium">{t("experiments.shared.armCohort.datasetGroup")}</th>
            <th className="px-3 py-1.5 font-medium">{t("experiments.shared.armCohort.cohort")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${row.arm}-${row.group}-${i}`} className="border-b border-outline/10 last:border-0">
              <td className="px-3 py-1.5 font-medium text-text-main">
                {row.arm}
                {row.reference ? (
                  <span className="ml-1 text-[10.5px] font-normal text-text-dim">· {t("experiments.shared.armCohort.control")}</span>
                ) : null}
              </td>
              <td className="px-3 py-1.5 text-text-variant">{row.group}</td>
              <td className="px-3 py-1.5 text-text-variant">
                {row.error ? (
                  <span
                    className="inline-flex items-start gap-1 text-danger"
                    title={row.error}
                  >
                    <Sym
                      name="error"
                      size={12}
                      className="mt-[1px] shrink-0"
                    />
                    <span className="leading-snug">{row.error}</span>
                  </span>
                ) : row.pending ? (
                  <span className="flex items-center gap-2">
                    <span className="relative h-1.5 w-24 overflow-hidden rounded-full bg-surface-high/60">
                      <span className="rb-indeterminate bg-secondary" />
                    </span>
                    <span className="text-[11px] text-text-dim">{t("experiments.shared.armCohort.synthesizing")}</span>
                  </span>
                ) : row.n != null && row.n > 0 ? (
                  <>
                    {t("experiments.shared.armCohort.personas", { count: row.n })}
                    {!sharedPool && row.pool ? (
                      <span className="ml-1 font-mono text-[10.5px] text-text-dim">
                        {poolSlug(row.pool)}
                      </span>
                    ) : null}
                  </>
                ) : (
                  <span className="text-text-dim">{emptyLabel}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MetricContractSummary({
  contract,
}: {
  contract: ExperimentMetricContract;
}) {
  const { t } = useI18n();
  const roleLabels: Record<string, string> = {
    Primary: t("experiments.shared.metric.role.primary"),
    Secondary: t("experiments.shared.metric.role.secondary"),
    Guardrail: t("experiments.shared.metric.role.guardrail"),
  };
  const groups: [string, string[] | undefined, string][] = [
    ["Primary", contract.primary, "bg-primary/12 text-primary"],
    ["Secondary", contract.secondary, "bg-secondary/12 text-secondary"],
    ["Guardrail", contract.guardrail, "bg-warn/12 text-warn"],
  ];
  const any = groups.some(([, keys]) => (keys?.length ?? 0) > 0);
  if (!any) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {groups.map(([label, keys, cls]) =>
        keys && keys.length > 0 ? (
          <div
            key={label}
            className="flex flex-wrap items-center gap-1.5 text-[11.5px]"
          >
            <span className="w-16 text-text-dim">{roleLabels[label] ?? label}</span>
            {keys.map((k) => (
              <span
                key={k}
                title={k}
                className={`rounded-md px-2 py-0.5 font-medium ${cls}`}
              >
                {humanizeToken(k)}
              </span>
            ))}
          </div>
        ) : null,
      )}
    </div>
  );
}
