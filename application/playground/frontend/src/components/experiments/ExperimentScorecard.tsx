import { useMemo } from "react";

import { useI18n } from "@/i18n/I18nProvider";
import type { MessageKey } from "@/i18n/types";
import type { ExperimentAnalysis, ExperimentComparison } from "@/lib/types";
import { translateMetricDescription } from "@/lib/metricInfo";
import { Sym } from "../cockpit/cockpitShared";
import { StudioGlassPanel } from "../studio/StudioShell";
import { MetaChip, SectionHeader } from "./experimentShared";

/**
 * Statsig/Eppo-style scorecard. Reads top-to-bottom:
 *   1. Confidence control + correction settings + cohort exposures.
 *   2. One section per metric role (Primary → Secondary → Guardrail), each with
 *      its own centred-on-0% axis.
 *   3. Numbered metrics inside each section; every metric stacks one
 *      confidence-interval bar per treatment arm (vs. control) sharing the axis,
 *      with each arm's point estimate ± margin on the right.
 */
export interface ExperimentScorecardProps {
  analysis: ExperimentAnalysis | undefined;
  loading: boolean;
  pending: boolean;
  live: boolean;
  confidence: number;
  onConfidenceChange: (confidence: number) => void;
  /** When true, significance uses Benjamini–Hochberg FDR (off by default). */
  fdr: boolean;
  onFdrChange: (fdr: boolean) => void;
}

const CONFIDENCE_OPTIONS = [0.8, 0.85, 0.9, 0.95, 0.99];

const ROLE_SECTIONS: { role: string; label: string; dot: string }[] = [
  { role: "primary", label: "Primary", dot: "bg-primary" },
  { role: "secondary", label: "Secondary", dot: "bg-secondary" },
  { role: "guardrail", label: "Guardrail", dot: "bg-warn" },
];

function roleLabelKey(role: string): MessageKey {
  if (role === "primary") return "experiments.scorecard.role.primary";
  if (role === "guardrail") return "experiments.scorecard.role.guardrail";
  return "experiments.scorecard.role.secondary";
}

// Stable identity palette for treatment arms (cycles if needed).
const ARM_COLORS = ["bg-primary", "bg-secondary", "bg-accent", "bg-warn", "bg-danger"];

const ROW_H = 24; // px per arm row — keeps left legend, plot and delta aligned

export function ExperimentScorecard({
  analysis,
  loading,
  pending,
  live,
  confidence,
  onConfidenceChange,
  fdr,
  onFdrChange,
}: ExperimentScorecardProps) {
  const { t } = useI18n();
  const armColors = useMemo(() => buildArmColors(analysis), [analysis]);
  const sections = useMemo(() => groupByRole(analysis?.comparisons ?? []), [analysis]);
  const exposures = useMemo(() => buildExposures(analysis), [analysis]);
  const hasData = sections.some((s) => s.metrics.length > 0);

  return (
    <StudioGlassPanel className="p-4">
      <SectionHeader
        icon="verified"
        title={t("experiments.scorecard.title")}
        right={
          <>
            <ConfidenceControl value={confidence} onChange={onConfidenceChange} />
            <FdrControl value={fdr} onChange={onFdrChange} />
            {analysis ? (
              <MetaChip tone="neutral">
                {correctionLabel(analysis.correction.method)} ·{" "}
                {t("experiments.scorecard.tests", { count: analysis.correction.count })}
              </MetaChip>
            ) : null}
            {live ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-secondary/12 px-2 py-0.5 text-[11px] font-medium text-secondary">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-secondary" />
                {t("experiments.scorecard.live")}
              </span>
            ) : null}
          </>
        }
      />

      {pending ? (
        <p className="mt-3 text-[12.5px] text-text-dim">
          {t("experiments.scorecard.waiting")}
        </p>
      ) : loading && !analysis ? (
        <p className="mt-3 text-[12.5px] text-text-dim">
          {t("experiments.scorecard.computing")}
        </p>
      ) : !hasData ? (
        <p className="mt-3 text-[12.5px] text-text-dim">
          {t("experiments.scorecard.noComparisons")}
        </p>
      ) : (
        <div className="mt-3 space-y-4">
          {exposures.length > 0 ? <ExposuresBlock exposures={exposures} /> : null}
          <div className="space-y-5">
            {sections.map((section) =>
              section.metrics.length > 0 ? (
                <RoleSection
                  key={section.role}
                  section={section}
                  armColors={armColors}
                  armSizes={analysis?.armSizes ?? {}}
                  baselineCell={analysis?.baselineCell ?? null}
                />
              ) : null,
            )}
          </div>
        </div>
      )}
    </StudioGlassPanel>
  );
}

// -- confidence control --------------------------------------------------------

function ConfidenceControl({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  const { t } = useI18n();
  return (
    <label className="inline-flex items-center gap-1.5 rounded-md bg-surface-high/60 px-2 py-0.5 text-[11.5px] font-medium text-text-variant">
      <Sym name="tune" size={13} className="text-text-dim" />
      <span className="text-text-dim">{t("experiments.scorecard.confidence")}</span>
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="cursor-pointer rounded bg-transparent font-semibold text-text-main outline-none focus:text-primary"
      >
        {CONFIDENCE_OPTIONS.map((c) => (
          <option key={c} value={c} className="bg-surface text-text-main">
            {Math.round(c * 100)}%
          </option>
        ))}
      </select>
    </label>
  );
}

function FdrControl({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <label
      className="inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-surface-high/60 px-2 py-0.5 text-[11.5px] font-medium text-text-variant"
      title={t("experiments.scorecard.fdrTooltip")}
    >
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3 w-3 accent-primary"
      />
      <span className="text-text-dim">FDR</span>
      <span className="font-semibold text-text-main">
        {value ? t("experiments.scorecard.fdrOn") : t("experiments.scorecard.fdrOff")}
      </span>
    </label>
  );
}

// -- arm identity colours ------------------------------------------------------

function buildArmColors(analysis: ExperimentAnalysis | undefined): Map<string, string> {
  const map = new Map<string, string>();
  if (!analysis) return map;
  let i = 0;
  for (const cmp of analysis.comparisons) {
    const key = cmp.cellId ?? cmp.arm ?? "";
    if (!key || map.has(key)) continue;
    map.set(key, ARM_COLORS[i % ARM_COLORS.length]);
    i += 1;
  }
  return map;
}

// -- exposures / cohort sizes --------------------------------------------------

/** "Onboarding framing=Feature-framed" → "Feature-framed" when factor=level. */
function shortArmLabel(label: string): string {
  const s = label.trim();
  const eq = s.lastIndexOf("=");
  if (eq > 0 && eq < s.length - 1 && !s.includes(" · ")) {
    return s.slice(eq + 1).trim() || s;
  }
  return s;
}

interface Exposure {
  cellId: string;
  label: string;
  n: number;
  pct: number;
  baseline: boolean;
  dot: string;
}

function buildExposures(analysis: ExperimentAnalysis | undefined): Exposure[] {
  if (!analysis) return [];
  const labels = new Map<string, string>();
  for (const cmp of analysis.comparisons) {
    const key = cmp.cellId ?? cmp.arm ?? "";
    if (key && cmp.arm && !labels.has(key)) labels.set(key, cmp.arm);
  }
  const sizes = analysis.armSizes ?? {};
  const keys = Object.keys(sizes);
  if (keys.length === 0) return [];
  const total = keys.reduce((sum, k) => sum + (sizes[k] || 0), 0) || 1;
  const ordered = keys.sort((a, b) => {
    if (a === analysis.baselineCell) return -1;
    if (b === analysis.baselineCell) return 1;
    return (sizes[b] || 0) - (sizes[a] || 0);
  });
  let treatmentIdx = 0;
  return ordered.map((cellId) => {
    const baseline = cellId === analysis.baselineCell;
    const dot = baseline ? "bg-text-dim" : ARM_COLORS[treatmentIdx++ % ARM_COLORS.length];
    const concrete = shortArmLabel(
      labels.get(cellId) || (baseline ? analysis.baselineArm : null) || cellId,
    );
    return {
      cellId,
      label: concrete,
      n: sizes[cellId] || 0,
      pct: ((sizes[cellId] || 0) / total) * 100,
      baseline,
      dot,
    };
  });
}

function ExposuresBlock({ exposures }: { exposures: Exposure[] }) {
  const { t } = useI18n();
  const total = exposures.reduce((s, e) => s + e.n, 0);
  return (
    <div className="rounded-lg border border-outline/25 bg-surface-high/20 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <Sym name="groups" size={14} className="text-text-dim" />
        <span className="text-[11px] font-semibold uppercase tracking-wide text-text-dim">
          {t("experiments.scorecard.trials")}
        </span>
        <span className="ml-auto text-[11px] text-text-dim">
          {t("experiments.scorecard.totalTrials", { count: total })}
        </span>
      </div>
      {/* one full-width bar split into per-arm segments (share of total, not progress) */}
      <div className="flex h-2.5 w-full gap-px overflow-hidden rounded-full bg-surface/60">
        {exposures.map((e) => (
          <div
            key={e.cellId}
            className={`h-full ${e.dot} first:rounded-l-full last:rounded-r-full`}
            style={{ width: `${e.pct}%` }}
            title={t("experiments.scorecard.exposureTooltip", {
              label: e.label,
              count: e.n,
              pct: e.pct.toFixed(1),
            })}
          />
        ))}
      </div>
      <div className="mt-2 space-y-1">
        {exposures.map((e) => (
          <div key={e.cellId} className="flex items-center gap-2.5">
            <span className={`h-2 w-2 shrink-0 rounded-sm ${e.dot}`} />
            <span className="flex-1 truncate text-[12px] text-text-main" title={e.label}>
              {e.label}
              {e.baseline ? (
                <span className="ml-1 text-[10px] font-medium text-text-dim">
                  ({t("experiments.scorecard.control")})
                </span>
              ) : null}
            </span>
            <span className="w-16 shrink-0 text-right text-[12px] font-semibold text-text-main tabular-nums">
              {e.n.toLocaleString()}
            </span>
            <span className="w-12 shrink-0 text-right text-[11px] text-text-dim tabular-nums">
              {e.pct.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// -- role → metric → arms grouping ---------------------------------------------

interface MetricGroup {
  metricKey: string;
  rows: ExperimentComparison[];
}

interface RoleGroup {
  role: string;
  label: string;
  dot: string;
  metrics: MetricGroup[];
}

function groupByRole(comparisons: ExperimentComparison[]): RoleGroup[] {
  const roleOf = (r: string) =>
    ROLE_SECTIONS.some((s) => s.role === r) ? r : "secondary";
  return ROLE_SECTIONS.map((section) => {
    const metrics = new Map<string, ExperimentComparison[]>();
    for (const cmp of comparisons) {
      if (roleOf(cmp.role) !== section.role) continue;
      const list = metrics.get(cmp.metricKey) ?? [];
      list.push(cmp);
      metrics.set(cmp.metricKey, list);
    }
    return {
      ...section,
      metrics: [...metrics.entries()].map(([metricKey, rows]) => ({ metricKey, rows })),
    };
  });
}

function RoleSection({
  section,
  armColors,
  armSizes,
  baselineCell,
}: {
  section: RoleGroup;
  armColors: Map<string, string>;
  armSizes: Record<string, number>;
  baselineCell: string | null;
}) {
  const { t: translate } = useI18n();
  const allRows = section.metrics.flatMap((m) => m.rows);
  const domain = useMemo(() => scaleDomain(allRows), [allRows]);
  const ticks = [-domain, -domain / 2, 0, domain / 2, domain];

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${section.dot}`} />
        <h3 className="font-display text-[13.5px] font-semibold text-text-main">
          {translate(roleLabelKey(section.role))}
        </h3>
        <span className="text-[11px] text-text-dim">
          {translate("experiments.scorecard.metricsCount", { count: section.metrics.length })}
        </span>
      </div>
      <div className="overflow-hidden rounded-lg border border-outline/25">
        {/* axis header */}
        <div className="flex items-stretch border-b border-outline/25 bg-surface-high/30 text-[10.5px] text-text-dim">
          <div className="w-[38%] shrink-0 px-3 py-1.5 font-medium">
            {translate("experiments.scorecard.metric")}
          </div>
          <div className="relative flex-1 py-1.5">
            {ticks.map((t, i) => (
              <span
                key={i}
                className="absolute -translate-x-1/2 whitespace-nowrap"
                style={{ left: `${valueToPct(t, domain)}%` }}
              >
                {t === 0 ? "0%" : `${t > 0 ? "+" : ""}${fmtPct(t)}`}
              </span>
            ))}
          </div>
          <div className="w-[128px] shrink-0 px-3 py-1.5 text-right font-medium">
            {translate("experiments.scorecard.deltaPct")}
          </div>
        </div>
        {section.metrics.map((metric, i) => (
          <MetricBlock
            key={metric.metricKey}
            index={i + 1}
            metric={metric}
            domain={domain}
            ticks={ticks}
            armColors={armColors}
            armSizes={armSizes}
            baselineCell={baselineCell}
            zebra={i % 2 === 1}
          />
        ))}
      </div>
    </div>
  );
}

function MetricBlock({
  index,
  metric,
  domain,
  ticks,
  armColors,
  armSizes,
  baselineCell,
  zebra,
}: {
  index: number;
  metric: MetricGroup;
  domain: number;
  ticks: number[];
  armColors: Map<string, string>;
  armSizes: Record<string, number>;
  baselineCell: string | null;
  zebra: boolean;
}) {
  const { t } = useI18n();
  const bg = zebra ? "bg-surface/30" : "";
  const first = metric.rows[0];
  const desc = translateMetricDescription(t, metric.metricKey);
  return (
    <div className={`border-b border-outline/12 last:border-0 ${bg}`}>
      {/* metric title row */}
      <div className="flex items-center gap-1.5 px-3 pt-2">
        <span className="text-[11px] font-semibold text-text-dim tabular-nums">{index}.</span>
        <span
          className="truncate text-[12.5px] font-medium text-text-main"
          title={metric.metricKey}
        >
          {humanizeMetric(metric.metricKey)}
        </span>
        {first?.kind && first.kind !== "numerical" ? (
          <span className="rounded bg-surface-high/60 px-1.5 py-0.5 text-[9.5px] uppercase tracking-wide text-text-dim">
            {kindLabel(t, first.kind)}
          </span>
        ) : null}
      </div>
      {desc ? (
        <p className="px-3 pl-8 pt-0.5 text-[11px] leading-snug text-text-dim">
          {desc}
        </p>
      ) : null}
      {/* category color legend (categorical metrics only) */}
      {first?.kind === "categorical" && (first.categories?.length ?? 0) > 0 ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pl-8 pt-1.5">
          {first.categories!.map((c, i) => (
            <span
              key={c}
              className="inline-flex items-center gap-1 text-[10px] text-text-dim"
              title={c}
            >
              <span className={`h-2 w-2 shrink-0 rounded-sm ${catColor(i)}`} />
              <span className="max-w-[140px] truncate">{c}</span>
            </span>
          ))}
        </div>
      ) : null}
      {/* one row per treatment arm */}
      <div className="pb-2 pt-1">
        {metric.rows.map((cmp, ai) => {
          const armColor = armColors.get(cmp.cellId ?? cmp.arm ?? "") ?? "bg-primary";
          return (
            <div key={`${cmp.cellId}-${ai}`} className="flex items-stretch">
              <div
                className="flex w-[38%] shrink-0 items-center gap-1.5 px-3"
                style={{ height: ROW_H }}
              >
                <span className={`h-2 w-2 shrink-0 rounded-sm ${armColor}`} />
                <span
                  className="truncate text-[11.5px] text-text-variant"
                  title={`${shortArmLabel(cmp.arm ?? cmp.cellId ?? "")} — ${sideSummary(cmp)}`}
                >
                  {shortArmLabel(cmp.arm ?? cmp.cellId ?? "")}
                </span>
                {(() => {
                  const note = coverageNote(cmp, armSizes, baselineCell);
                  return note ? (
                    <span
                      className="ml-auto shrink-0 text-[10px] font-medium text-warn tabular-nums"
                      title={t("experiments.scorecard.coverageTooltip", {
                        metric: metric.metricKey,
                      })}
                    >
                      {note}
                    </span>
                  ) : null;
                })()}
              </div>
              <div className="flex flex-1 items-center" style={{ height: ROW_H }}>
                <CiBar cmp={cmp} domain={domain} ticks={ticks} />
              </div>
              <div
                className="flex w-[128px] shrink-0 items-center justify-end gap-1 px-3"
                style={{ height: ROW_H }}
              >
                <DeltaValue cmp={cmp} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Stable per-category swatch palette (index into cmp.categories order). */
const CAT_COLORS = [
  "bg-sky-500",
  "bg-violet-500",
  "bg-emerald-500",
  "bg-amber-500",
  "bg-rose-500",
  "bg-cyan-500",
  "bg-fuchsia-500",
  "bg-lime-500",
  "bg-indigo-500",
  "bg-teal-500",
];

const catColor = (i: number) => CAT_COLORS[i % CAT_COLORS.length];

/** Localized kind badge label (metric kinds are UI chrome, not data). */
function kindLabel(t: (key: MessageKey) => string, kind: string): string {
  if (kind === "categorical") return t("experiments.scorecard.kind.categorical");
  if (kind === "textual") return t("experiments.scorecard.kind.textual");
  return kind;
}

const CATEGORICAL_INSUFFICIENT_KEYS = {
  textual: "experiments.scorecard.insufficient.textual",
  tooFewResponses: "experiments.scorecard.insufficient.tooFewResponses",
  singleCategory: "experiments.scorecard.insufficient.singleCategory",
  default: "experiments.scorecard.insufficient.default",
} as const satisfies Record<string, MessageKey>;

function categoricalInsufficientBucket(
  cmp: ExperimentComparison,
): keyof typeof CATEGORICAL_INSUFFICIENT_KEYS {
  if (cmp.test === "skipped") return "textual";
  switch (cmp.reason) {
    case "too_few_responses":
      return "tooFewResponses";
    case "single_category":
      return "singleCategory";
    default:
      return "default";
  }
}

function CiBar({
  cmp,
  domain,
  ticks,
}: {
  cmp: ExperimentComparison;
  domain: number;
  ticks: number[];
}) {
  const { t } = useI18n();
  // Categorical / textual: show the arm's category mix as a stacked proportion
  // bar (a categorical shift is a distribution, not a point on the ±% axis).
  if (cmp.kind !== "numerical") {
    const dist = cmp.treatment?.distribution;
    const cats =
      cmp.categories && cmp.categories.length > 0
        ? cmp.categories
        : dist
          ? Object.keys(dist)
          : [];
    const hasDist = Boolean(dist) && cats.some((c) => (dist?.[c] ?? 0) > 0);
    if (!hasDist) {
      return (
        <div className="relative h-full w-full">
          <GridLines domain={domain} ticks={ticks} />
          <ZeroLine domain={domain} />
          <div className="flex h-full items-center pl-2 text-[10.5px] text-text-dim">
            {t(CATEGORICAL_INSUFFICIENT_KEYS[categoricalInsufficientBucket(cmp)])}
          </div>
        </div>
      );
    }
    return (
      <div className="flex h-full w-full items-center pr-3">
        <div className="flex h-2.5 w-full overflow-hidden rounded-sm bg-surface-high/40 ring-1 ring-inset ring-outline/15">
          {cats.map((c, i) => {
            const p = dist?.[c] ?? 0;
            if (p <= 0) return null;
            return (
              <div
                key={c}
                className={catColor(i)}
                style={{ width: `${p * 100}%` }}
                title={`${c}: ${Math.round(p * 100)}%`}
              />
            );
          })}
        </div>
      </div>
    );
  }
  const ci =
    cmp.effect?.ciPct ??
    (typeof cmp.effect?.deltaPct === "number"
      ? ([cmp.effect.deltaPct, cmp.effect.deltaPct] as [number, number])
      : undefined);
  const delta = cmp.effect?.deltaPct;
  if (!ci || typeof delta !== "number") {
    return (
      <div className="relative h-full w-full">
        <GridLines domain={domain} ticks={ticks} />
        <ZeroLine domain={domain} />
        <div className="flex h-full items-center pl-2 text-[10.5px] text-text-dim">
          {cmp.test === "insufficient_data"
            ? t("experiments.scorecard.insufficient.default")
            : "—"}
        </div>
      </div>
    );
  }
  const [lo, hi] = ci;
  const loClamped = lo < -domain;
  const hiClamped = hi > domain;
  const left = valueToPct(clamp(lo, domain), domain);
  const right = valueToPct(clamp(hi, domain), domain);
  const width = Math.max(right - left, 1.2);
  const center = valueToPct(clamp(delta, domain), domain);
  const color = barColor(cmp);
  return (
    <div className="relative h-full w-full">
      <GridLines domain={domain} ticks={ticks} />
      <ZeroLine domain={domain} />
      <div
        className={`absolute top-1/2 h-[7px] -translate-y-1/2 rounded-full ${color.bar}`}
        style={{ left: `${left}%`, width: `${width}%` }}
      />
      {!loClamped ? (
        <div
          className={`absolute top-1/2 h-[11px] w-[2px] -translate-x-1/2 -translate-y-1/2 rounded ${color.cap}`}
          style={{ left: `${left}%` }}
        />
      ) : null}
      {!hiClamped ? (
        <div
          className={`absolute top-1/2 h-[11px] w-[2px] -translate-x-1/2 -translate-y-1/2 rounded ${color.cap}`}
          style={{ left: `${right}%` }}
        />
      ) : null}
      <div
        className={`absolute top-1/2 h-[12px] w-[3px] -translate-x-1/2 -translate-y-1/2 rounded ${color.tick}`}
        style={{ left: `${center}%` }}
      />
    </div>
  );
}

/**
 * Delta cell. Significant movers get a tinted chip + directional caret (▲/▼) so
 * they pop; non-significant results stay plainly muted. Colour = direction
 * (green good / red bad), presence-of-colour = statistically significant.
 */
function DeltaValue({ cmp }: { cmp: ExperimentComparison }) {
  const delta = deltaText(cmp);
  const margin = marginOrP(cmp);
  if (!cmp.significant) {
    return (
      <>
        <span className="text-[12px] font-medium tabular-nums text-text-variant">{delta}</span>
        {margin ? (
          <span className="text-[10px] text-text-dim tabular-nums">{margin}</span>
        ) : null}
      </>
    );
  }
  const good = isGood(cmp);
  const chip = good ? "bg-secondary/12 text-secondary" : "bg-danger/12 text-danger";
  const caret = deltaDirection(cmp);
  return (
    <>
      <span
        className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[12px] font-semibold tabular-nums ${chip}`}
      >
        {caret ? <span className="text-[9px] leading-none">{caret}</span> : null}
        {delta}
      </span>
      {margin ? <span className="text-[10px] text-text-dim tabular-nums">{margin}</span> : null}
    </>
  );
}

function isGood(cmp: ExperimentComparison): boolean {
  const diff = cmp.effect?.diff ?? cmp.effect?.deltaPct ?? 0;
  if (cmp.role === "guardrail") return diff >= 0;
  return diff >= 0;
}

function deltaDirection(cmp: ExperimentComparison): string {
  const d =
    typeof cmp.effect?.deltaPct === "number"
      ? cmp.effect.deltaPct
      : typeof cmp.effect?.diff === "number"
        ? cmp.effect.diff
        : 0;
  if (d > 0) return "▲";
  if (d < 0) return "▼";
  return "";
}

function GridLines({ domain, ticks }: { domain: number; ticks: number[] }) {
  return (
    <>
      {ticks.map((t, i) =>
        t === 0 ? null : (
          <div
            key={i}
            className="absolute inset-y-0 w-px bg-outline/12"
            style={{ left: `${valueToPct(t, domain)}%` }}
          />
        ),
      )}
    </>
  );
}

function ZeroLine({ domain }: { domain: number }) {
  return (
    <div
      className="absolute inset-y-0 w-px bg-outline/50"
      style={{ left: `${valueToPct(0, domain)}%` }}
    />
  );
}

// -- scale + formatting helpers ------------------------------------------------

function scaleDomain(rows: ExperimentComparison[]): number {
  let max = 0;
  for (const cmp of rows) {
    if (cmp.kind !== "numerical" || !cmp.effect) continue;
    const ci = cmp.effect.ciPct;
    if (ci) max = Math.max(max, Math.abs(ci[0]), Math.abs(ci[1]));
    if (typeof cmp.effect.deltaPct === "number") max = Math.max(max, Math.abs(cmp.effect.deltaPct));
  }
  if (max <= 0) return 10;
  const padded = max * 1.15;
  const mag = Math.pow(10, Math.floor(Math.log10(padded)));
  return Math.ceil(padded / mag) * mag;
}

function valueToPct(value: number, domain: number): number {
  return ((value + domain) / (2 * domain)) * 100;
}

function clamp(value: number, domain: number): number {
  return Math.max(-domain, Math.min(domain, value));
}

function fmtPct(v: number): string {
  const abs = Math.abs(v);
  return abs >= 10 ? v.toFixed(0) + "%" : v.toFixed(1) + "%";
}

function humanizeMetric(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function deltaText(cmp: ExperimentComparison): string {
  if (cmp.kind === "numerical" && typeof cmp.effect?.deltaPct === "number") {
    const d = cmp.effect.deltaPct;
    return `${d >= 0 ? "+" : ""}${d.toFixed(1)}%`;
  }
  if (cmp.kind === "numerical" && typeof cmp.effect?.diff === "number") {
    const d = cmp.effect.diff;
    return `${d >= 0 ? "+" : ""}${d.toFixed(2)}`;
  }
  if (cmp.kind === "categorical" && typeof cmp.effect?.cramersV === "number") {
    return `V=${cmp.effect.cramersV.toFixed(2)}`;
  }
  return "—";
}

/** "±X.X%" from the CI half-width when available, else the adjusted p-value. */
function marginOrP(cmp: ExperimentComparison): string {
  const ci = cmp.effect?.ciPct;
  if (cmp.kind === "numerical" && ci && typeof cmp.effect?.deltaPct === "number") {
    const margin = Math.abs(ci[1] - ci[0]) / 2;
    if (Number.isFinite(margin) && margin > 0) return `±${margin.toFixed(1)}%`;
  }
  return pText(cmp);
}

function barColor(cmp: ExperimentComparison): { bar: string; tick: string; cap: string } {
  if (!cmp.significant)
    return { bar: "bg-outline/45", tick: "bg-text-main", cap: "bg-text-dim/70" };
  const diff = cmp.effect?.diff ?? 0;
  const bad = diff < 0;
  return bad
    ? { bar: "bg-danger/55", tick: "bg-danger", cap: "bg-danger/80" }
    : { bar: "bg-secondary/55", tick: "bg-secondary", cap: "bg-secondary/80" };
}

/**
 * Per-metric sample note. Returns null when this metric's baseline/treatment n
 * matches the arm allocation (fully covered — the allocation block already shows
 * it). Returns "n b/t" only when coverage falls short, flagging missing data.
 */
function coverageNote(
  cmp: ExperimentComparison,
  armSizes: Record<string, number>,
  baselineCell: string | null,
): string | null {
  const baseN = cmp.baseline?.n ?? 0;
  const treatN = cmp.treatment?.n ?? 0;
  const baseAlloc = baselineCell ? armSizes[baselineCell] : undefined;
  const treatAlloc = cmp.cellId ? armSizes[cmp.cellId] : undefined;
  const fullyCovered =
    (baseAlloc === undefined || baseN === baseAlloc) &&
    (treatAlloc === undefined || treatN === treatAlloc);
  if (fullyCovered) return null;
  return `n ${baseN}/${treatN}`;
}

function sideSummary(cmp: ExperimentComparison): string {
  const b = cmp.baseline;
  const t = cmp.treatment;
  if (cmp.kind === "numerical") {
    const bm = typeof b?.mean === "number" ? b.mean.toFixed(2) : "—";
    const tm = typeof t?.mean === "number" ? t.mean.toFixed(2) : "—";
    return `${bm} → ${tm} · n ${b?.n ?? 0}/${t?.n ?? 0}`;
  }
  return `n ${b?.n ?? 0}/${t?.n ?? 0}`;
}

function pText(cmp: ExperimentComparison): string {
  const p = cmp.pValueAdj ?? cmp.pValue;
  if (typeof p !== "number") return "";
  return p < 0.001 ? "p<0.001" : `p=${p.toFixed(3)}`;
}

function correctionLabel(method: string | undefined): string {
  if (!method) return "correction";
  const m = method.toLowerCase();
  if (m.includes("bh") || m.includes("benjamini")) return "BH";
  if (m.includes("bonferroni")) return "Bonferroni";
  if (m === "none") return "no correction";
  return method;
}
