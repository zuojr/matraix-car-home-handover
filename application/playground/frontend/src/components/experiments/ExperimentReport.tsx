import { useEffect } from "react";

import type {
  ExperimentAnalysis,
  ExperimentComparison,
  ExperimentManifest,
  ExperimentPersonaSlices,
  ExperimentSliceDriver,
} from "@/lib/types";
import { useI18n } from "@/i18n/I18nProvider";
import type { MessageKey } from "@/i18n/types";
import { translateMetricDescription } from "@/lib/metricInfo";
import { Sym } from "../cockpit/cockpitShared";

/**
 * Print-ready experiment report. Rendered as a light-themed A4-style document
 * inside a full-screen overlay; "Save as PDF" uses the browser print flow so the
 * output is crisp, vector, and selectable. Print CSS (index.css `.exp-report`)
 * hides everything else on the page.
 *
 * Covers the whole experiment: setup profile, results scorecard, and the full
 * statistical analysis — the same content as the on-screen tabs, laid out for a
 * shareable deliverable.
 */
export function ExperimentReportOverlay({
  manifest,
  analysis,
  analysisLoading = false,
  open,
  onClose,
}: {
  manifest: ExperimentManifest;
  analysis: ExperimentAnalysis | null;
  /** True while the slices-enabled report payload is still fetching. */
  analysisLoading?: boolean;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const ready = Boolean(analysis) && !analysisLoading;

  return (
    <div className="exp-report-overlay fixed inset-0 z-[60] overflow-auto bg-slate-900/70 backdrop-blur-sm">
      <div className="no-print sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-slate-700 bg-slate-900/90 px-4 py-2.5 text-slate-100">
        <div className="flex items-center gap-2 text-[13px] font-medium">
          <Sym name="description" size={16} />
          {t("experiments.report.preview")}
          {analysisLoading ? (
            <span className="text-[11.5px] font-normal text-amber-300">
              · {t("experiments.report.preparingFull")}
            </span>
          ) : ready ? (
            <span className="text-[11.5px] font-normal text-emerald-300">
              · {t("experiments.report.ready")}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => window.print()}
            disabled={!ready}
            className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-[12.5px] font-semibold text-slate-900 transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Sym name="picture_as_pdf" size={15} />
            {analysisLoading
              ? t("experiments.report.preparingFull")
              : t("experiments.report.saveAsPdf")}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-600 px-3 py-1.5 text-[12.5px] font-medium text-slate-200 transition hover:bg-slate-800"
          >
            <Sym name="close" size={15} />
            {t("experiments.report.close")}
          </button>
        </div>
      </div>

      <ReportDoc
        manifest={manifest}
        analysis={analysis}
        analysisLoading={analysisLoading}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Document
// ---------------------------------------------------------------------------

function ReportDoc({
  manifest,
  analysis,
  analysisLoading = false,
}: {
  manifest: ExperimentManifest;
  analysis: ExperimentAnalysis | null;
  analysisLoading?: boolean;
}) {
  const { t } = useI18n();
  const axis = (manifest.axis ?? "sut").toUpperCase();
  const trials = manifest.progress ?? { trialCount: 0, completedTrials: 0 };
  const alpha = analysis?.correction.alpha ?? 0.05;
  const arms = reportArms(manifest);
  const sections = groupByRole(analysis?.comparisons ?? []);
  const hasResults = sections.some((s) => s.metrics.length > 0);
  const armColors = analysis ? buildArmColors(analysis) : new Map<string, string>();

  const facts: Array<[string, string]> = [
    ["Axis", axis === "PUT" ? "PUT · persona under test" : "SUT · system under test"],
    ["Design", (manifest.design.effectiveType || manifest.design.type || "—").replace(/_/g, " ")],
    ["Persona model", manifest.personaModel?.split("/").pop() || manifest.personaModel || "—"],
    ["Arms", String(arms.length || manifest.cells.length)],
    [
      "Trials",
      trials.trialCount > 0
        ? `${trials.completedTrials}/${trials.trialCount} complete`
        : String(trials.completedTrials),
    ],
    ["Cohort", cohortSummary(manifest)],
    ["Seed", String(manifest.sampling.seed)],
    ["Cost", typeof manifest.costUsd === "number" ? `$${manifest.costUsd.toFixed(3)}` : "—"],
    ["Duration", typeof manifest.durationSeconds === "number" ? fmtDuration(manifest.durationSeconds) : "—"],
    ["Confidence", `${Math.round((1 - alpha) * 100)}%`],
    [
      "Correction",
      analysis
        ? `${correctionLabel(analysis.correction.method)} · ${analysis.correction.count} tests`
        : "—",
    ],
    ["Status", manifest.status || "—"],
  ];

  return (
    <article className="exp-report mx-auto my-6 max-w-[860px] bg-white px-10 py-9 text-slate-800 shadow-2xl print:my-0 print:max-w-none print:px-0 print:py-0 print:shadow-none">
      {/* Cover / header */}
      <header className="border-b-2 border-slate-900 pb-4">
        <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          <span>MatrAIx · Persona Experiment</span>
          <span>{new Date().toLocaleString()}</span>
        </div>
        <h1 className="mt-3 font-semibold leading-tight text-slate-900" style={{ fontSize: 26 }}>
          {manifest.name || manifest.experimentId}
        </h1>
        <div className="mt-1 font-mono text-[12px] text-slate-500">{manifest.task}</div>
      </header>

      {manifest.hypothesis ? (
        <section className="mt-5 rounded-md border border-slate-200 bg-slate-50 p-3.5">
          <div className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-500">
            Hypothesis
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-slate-700">{manifest.hypothesis}</p>
        </section>
      ) : null}

      {/* Fact grid */}
      <section className="mt-5 grid grid-cols-3 gap-x-6 gap-y-3">
        {facts.map(([k, v]) => (
          <div key={k}>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{k}</div>
            <div className="mt-0.5 text-[13px] font-medium text-slate-800">{v}</div>
          </div>
        ))}
      </section>

      {/* Setup profile */}
      <ReportSection title={t("experiments.report.section.setup")} n={1}>
        <SubTitle>{t("experiments.report.sub.armsCohorts")}</SubTitle>
        <table className="w-full border-collapse text-[12px]">
          <thead>
            <Tr head>
              <Th>{t("experiments.report.col.arm")}</Th>
              {axis === "PUT" ? <Th>{t("experiments.report.col.testedValue")}</Th> : null}
              <Th align="right">{t("experiments.report.col.personas")}</Th>
              <Th>{t("experiments.report.col.cohort")}</Th>
            </Tr>
          </thead>
          <tbody>
            {arms.map((a, i) => (
              <Tr key={a.key} zebra={i % 2 === 1}>
                <Td>
                  {a.label}
                  {a.baseline ? (
                    <span className="ml-1 text-slate-400">· {t("experiments.report.baseline")}</span>
                  ) : null}
                </Td>
                {axis === "PUT" ? <Td>{a.value ?? "—"}</Td> : null}
                <Td align="right">{a.n != null ? a.n : "—"}</Td>
                <Td mono>{a.pool ? poolSlug(a.pool) : "—"}</Td>
              </Tr>
            ))}
          </tbody>
        </table>

        <SubTitle className="mt-4">{t("experiments.report.sub.metricContract")}</SubTitle>
        <div className="space-y-1.5">
          <ContractRow
            label={t("experiments.report.role.primary")}
            items={manifest.metricContract.primary}
          />
          <ContractRow
            label={t("experiments.report.role.secondary")}
            items={manifest.metricContract.secondary}
          />
          <ContractRow
            label={t("experiments.report.role.guardrail")}
            items={manifest.metricContract.guardrail}
          />
        </div>

        {manifest.cohortMix && manifest.cohortMix.dimensions.length > 0 ? (
          <>
            <SubTitle className="mt-4">{t("experiments.report.sub.cohortMix")}</SubTitle>
            <div className="space-y-2">
              {manifest.cohortMix.dimensions.map((dim) => (
                <div key={dim.id}>
                  <div className="text-[11.5px] font-medium text-slate-700">
                    {humanize(dim.id)}
                    <span className="ml-1 text-slate-400">· {dim.match}</span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
                    {dim.buckets.map((b) => (
                      <span key={b.value}>
                        {b.value} {Math.round(b.pct * 100)}%
                        {typeof b.expectedPct === "number"
                          ? ` (target ${Math.round(b.expectedPct * 100)}%)`
                          : ""}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : null}
      </ReportSection>

      {/* Results — mirrors on-screen Scorecard (exposures + forest) */}
      <ReportSection title={t("experiments.report.section.results")} n={2}>
        {!analysis ? (
          <Empty>{t("experiments.report.empty.noMetrics")}</Empty>
        ) : (
          <>
            <ExposureBlock analysis={analysis} />

            {hasResults ? (
              <div className="mt-4 space-y-4">
                {sections.map((s) =>
                  s.metrics.length > 0 ? (
                    <ForestSection
                      key={s.role}
                      role={s.role}
                      label={reportRoleLabel(t, s.role)}
                      metrics={s.metrics}
                      armColors={armColors}
                    />
                  ) : null,
                )}
              </div>
            ) : (
              <Empty>{t("experiments.report.empty.noComparisons")}</Empty>
            )}
          </>
        )}
      </ReportSection>

      {/* Analysis — mirrors Effect explorer + Heterogeneity drivers */}
      <ReportSection title={t("experiments.report.section.analysis")} n={3}>
        {!analysis || !hasResults ? (
          <Empty>{t("experiments.report.empty.noDetail")}</Empty>
        ) : (
          <>
            <SubTitle>{t("experiments.explore.effects")}</SubTitle>
            <EffectsTable analysis={analysis} />

            {analysis.sliceDrivers && analysis.sliceDrivers.length > 0 ? (
              <>
                <SubTitle className="mt-5">
                  {t("experiments.explore.drivers")}
                  {analysis.sliceDrivers[0]?.metricKey
                    ? ` · ${humanize(analysis.sliceDrivers[0].metricKey)}`
                    : ""}
                </SubTitle>
                <HeterogeneityDrivers analysis={analysis} />
                {analysis.slices && analysis.slices.rows.length > 0 ? (
                  <>
                    <SubTitle className="mt-4">
                      {t("experiments.explore.attribute")} · {humanize(analysis.slices.dimension)}
                    </SubTitle>
                    <SliceTable slices={analysis.slices} />
                  </>
                ) : null}
              </>
            ) : analysisLoading ? (
              <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800">
                {t("experiments.report.preparingFull")}
              </div>
            ) : null}

            <p className="mt-4 text-[10.5px] leading-relaxed text-slate-500">
              {t("experiments.report.footnote", {
                adjustment:
                  analysis.correction.method && analysis.correction.method !== "none"
                    ? t("experiments.report.footnoteAdjusted", {
                        method: correctionLabel(analysis.correction.method),
                        count: analysis.correction.count,
                      })
                    : t("experiments.report.footnoteUncorrected"),
                alpha,
              })}
            </p>
          </>
        )}
      </ReportSection>

      <footer className="mt-8 border-t border-slate-200 pt-3 text-[10px] text-slate-400">
        Generated by MatrAIx · {manifest.experimentId} · {new Date().toISOString()}
      </footer>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Results — match on-screen Scorecard
// ---------------------------------------------------------------------------

/** Print-safe hex for Scorecard arm identity (primary / secondary / accent / warn / danger). */
const ARM_HEX = ["#0076c2", "#009667", "#6d28d9", "#b07810", "#be3246"];
const ROLE_DOT_HEX: Record<string, string> = {
  primary: "#0076c2",
  secondary: "#009667",
  guardrail: "#b07810",
};

interface ExposureRow {
  cellId: string;
  label: string;
  n: number;
  pct: number;
  baseline: boolean;
  color: string;
}

function buildExposures(analysis: ExperimentAnalysis): ExposureRow[] {
  const labels = new Map<string, string>();
  for (const cmp of analysis.comparisons) {
    const key = cmp.cellId ?? cmp.arm ?? "";
    if (key && cmp.arm && !labels.has(key)) labels.set(key, cmp.arm);
  }
  const sizes = analysis.armSizes ?? {};
  const keys = Object.keys(sizes);
  if (keys.length === 0) return [];
  const total = keys.reduce((sum, k) => sum + (sizes[k] || 0), 0) || 1;
  const ordered = [...keys].sort((a, b) => {
    if (a === analysis.baselineCell) return -1;
    if (b === analysis.baselineCell) return 1;
    return (sizes[b] || 0) - (sizes[a] || 0);
  });
  let treatmentIdx = 0;
  return ordered.map((cellId) => {
    const baseline = cellId === analysis.baselineCell;
    const color = baseline ? "#94a3b8" : ARM_HEX[treatmentIdx++ % ARM_HEX.length];
    const concrete = shortArmLabel(
      labels.get(cellId) || (baseline ? analysis.baselineArm : null) || cellId,
    );
    return {
      cellId,
      label: concrete,
      n: sizes[cellId] || 0,
      pct: ((sizes[cellId] || 0) / total) * 100,
      baseline,
      color,
    };
  });
}

function buildArmColors(analysis: ExperimentAnalysis): Map<string, string> {
  const map = new Map<string, string>();
  let i = 0;
  for (const cmp of analysis.comparisons) {
    const key = cmp.cellId ?? cmp.arm ?? "";
    if (!key || map.has(key)) continue;
    map.set(key, ARM_HEX[i % ARM_HEX.length]);
    i += 1;
  }
  return map;
}

/** Stacked share bar + legend — same layout as Results → Scorecard exposures. */
function ExposureBlock({ analysis }: { analysis: ExperimentAnalysis }) {
  const { t } = useI18n();
  const exposures = buildExposures(analysis);
  if (exposures.length === 0) return null;
  const total = exposures.reduce((s, e) => s + e.n, 0);
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          {t("experiments.scorecard.trials")}
        </span>
        <span className="ml-auto text-[11px] text-slate-500">
          {t("experiments.scorecard.totalTrials", { count: total })}
        </span>
      </div>
      <div className="flex h-2.5 w-full gap-px overflow-hidden rounded-full bg-slate-200/70">
        {exposures.map((e) => (
          <div
            key={e.cellId}
            className="h-full first:rounded-l-full last:rounded-r-full"
            style={{ width: `${e.pct}%`, backgroundColor: e.color }}
            title={`${e.label} · ${e.n} · ${e.pct.toFixed(1)}%`}
          />
        ))}
      </div>
      <div className="mt-2 space-y-1">
        {exposures.map((e) => (
          <div key={e.cellId} className="flex items-center gap-2.5">
            <span
              className="h-2 w-2 shrink-0 rounded-sm"
              style={{ backgroundColor: e.color }}
            />
            <span className="min-w-0 flex-1 truncate text-[12px] text-slate-800" title={e.label}>
              {e.label}
              {e.baseline ? (
                <span className="ml-1 text-[10px] font-medium text-slate-400">
                  ({t("experiments.scorecard.control")})
                </span>
              ) : null}
            </span>
            <span className="w-16 shrink-0 text-right text-[12px] font-semibold tabular-nums text-slate-800">
              {e.n.toLocaleString()}
            </span>
            <span className="w-12 shrink-0 text-right text-[11px] tabular-nums text-slate-500">
              {e.pct.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// -- forest plot (mirrors the on-screen Scorecard) -----------------------------

const FOREST_LEFT = "38%"; // metric / arm label column
const FOREST_RIGHT = 128; // delta column (px)
const FOREST_ROW_H = 24; // px per arm row

interface ForestMetric {
  metricKey: string;
  rows: ExperimentComparison[];
}

function ForestSection({
  role,
  label,
  metrics,
  armColors,
}: {
  role: string;
  label: string;
  metrics: ForestMetric[];
  armColors: Map<string, string>;
}) {
  const { t } = useI18n();
  const allRows = metrics.flatMap((m) => m.rows);
  const domain = scaleDomain(allRows);
  const ticks = [-domain, -domain / 2, 0, domain / 2, domain];
  const roleDot = ROLE_DOT_HEX[role] ?? ROLE_DOT_HEX.secondary;
  return (
    <div className="break-inside-avoid">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: roleDot }} />
        <h3 className="text-[13.5px] font-semibold text-slate-800">{label}</h3>
        <span className="text-[11px] text-slate-400">
          {t("experiments.scorecard.metricsCount", { count: metrics.length })}
        </span>
      </div>
      <div className="overflow-hidden rounded-lg border border-slate-200">
        <div className="flex items-stretch border-b border-slate-200 bg-slate-50 text-[10.5px] text-slate-500">
          <div className="shrink-0 px-3 py-1.5 font-medium" style={{ width: FOREST_LEFT }}>
            {t("experiments.scorecard.metric")}
          </div>
          <div className="relative flex-1 py-1.5">
            {ticks.map((tick, i) => (
              <span
                key={i}
                className="absolute -translate-x-1/2 whitespace-nowrap"
                style={{ left: `${valueToPct(tick, domain)}%` }}
              >
                {tick === 0 ? "0%" : `${tick > 0 ? "+" : ""}${fmtPct(tick)}`}
              </span>
            ))}
          </div>
          <div
            className="shrink-0 px-3 py-1.5 text-right font-medium"
            style={{ width: FOREST_RIGHT }}
          >
            {t("experiments.scorecard.deltaPct")}
          </div>
        </div>
        {metrics.map((m, i) => (
          <ForestMetricBlock
            key={m.metricKey}
            index={i + 1}
            metric={m}
            domain={domain}
            ticks={ticks}
            armColors={armColors}
            zebra={i % 2 === 1}
          />
        ))}
      </div>
    </div>
  );
}

function ForestMetricBlock({
  index,
  metric,
  domain,
  ticks,
  armColors,
  zebra,
}: {
  index: number;
  metric: ForestMetric;
  domain: number;
  ticks: number[];
  armColors: Map<string, string>;
  zebra: boolean;
}) {
  const { t } = useI18n();
  const first = metric.rows[0];
  const categorical = first?.kind === "categorical";
  const cats =
    categorical && first?.categories && first.categories.length > 0 ? first.categories : [];
  const desc = translateMetricDescription(t, metric.metricKey);
  return (
    <div
      className={`break-inside-avoid border-b border-slate-100 last:border-0 ${
        zebra ? "bg-slate-50/60" : ""
      }`}
    >
      <div className="flex items-center gap-1.5 px-3 pt-2">
        <span className="text-[11px] font-semibold tabular-nums text-slate-400">{index}.</span>
        <span className="text-[12.5px] font-medium text-slate-800">{humanize(metric.metricKey)}</span>
        {first?.kind && first.kind !== "numerical" ? (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9.5px] uppercase tracking-wide text-slate-500">
            {first.kind === "categorical"
              ? t("experiments.scorecard.kind.categorical")
              : first.kind === "textual"
                ? t("experiments.scorecard.kind.textual")
                : first.kind}
          </span>
        ) : null}
      </div>
      {desc ? (
        <p className="px-3 pl-8 pt-0.5 text-[11px] leading-snug text-slate-500">{desc}</p>
      ) : null}
      {cats.length > 0 ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pl-8 pt-1.5">
          {cats.map((c, i) => (
            <span key={c} className="inline-flex items-center gap-1 text-[10px] text-slate-500">
              <span
                className="h-2 w-2 shrink-0 rounded-sm"
                style={{ backgroundColor: catHex(i) }}
              />
              <span className="max-w-[140px] truncate">{c}</span>
            </span>
          ))}
        </div>
      ) : null}
      <div className="pb-2 pt-1">
        {metric.rows.map((cmp, ai) => {
          const armColor = armColors.get(cmp.cellId ?? cmp.arm ?? "") ?? ARM_HEX[0];
          return (
            <div key={`${cmp.cellId}-${ai}`} className="flex items-stretch">
              <div
                className="flex shrink-0 items-center gap-1.5 px-3"
                style={{ width: FOREST_LEFT, height: FOREST_ROW_H }}
              >
                <span
                  className="h-2 w-2 shrink-0 rounded-sm"
                  style={{ backgroundColor: armColor }}
                />
                <span className="truncate text-[11.5px] text-slate-600">
                  {shortArmLabel(cmp.arm ?? cmp.cellId ?? "")}
                </span>
              </div>
              <div className="flex flex-1 items-center" style={{ height: FOREST_ROW_H }}>
                <ForestBar cmp={cmp} domain={domain} ticks={ticks} />
              </div>
              <div
                className="flex shrink-0 items-center justify-end gap-1 px-3"
                style={{ width: FOREST_RIGHT, height: FOREST_ROW_H }}
              >
                <ForestDelta cmp={cmp} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ForestDelta({ cmp }: { cmp: ExperimentComparison }) {
  const delta = deltaText(cmp);
  const margin = marginOrP(cmp);
  if (!cmp.significant) {
    return (
      <>
        <span className="text-[12px] font-medium tabular-nums text-slate-600">{delta}</span>
        {margin ? (
          <span className="text-[10px] tabular-nums text-slate-400">{margin}</span>
        ) : null}
      </>
    );
  }
  const good = isGoodDirection(cmp);
  const caret = deltaDirection(cmp);
  return (
    <>
      <span
        className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[12px] font-semibold tabular-nums ${
          good ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"
        }`}
      >
        {caret ? <span className="text-[9px] leading-none">{caret}</span> : null}
        {delta}
      </span>
      {margin ? <span className="text-[10px] tabular-nums text-slate-400">{margin}</span> : null}
    </>
  );
}

function isGoodDirection(cmp: ExperimentComparison): boolean {
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

function ForestBar({
  cmp,
  domain,
  ticks,
}: {
  cmp: ExperimentComparison;
  domain: number;
  ticks: number[];
}) {
  // Categorical: stacked distribution bar (a shift is a distribution, not a point).
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
          <ForestGrid domain={domain} ticks={ticks} />
          <div className="flex h-full items-center pl-2 text-[10.5px] text-slate-400">
            {insufficientText(cmp)}
          </div>
        </div>
      );
    }
    return (
      <div className="flex h-full w-full items-center pr-3">
        <div className="flex h-2.5 w-full overflow-hidden rounded-sm border border-slate-200 bg-slate-100">
          {cats.map((c, i) => {
            const p = dist?.[c] ?? 0;
            if (p <= 0) return null;
            return (
              <div key={c} style={{ width: `${p * 100}%`, backgroundColor: catHex(i) }} />
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
        <ForestGrid domain={domain} ticks={ticks} />
        <div className="flex h-full items-center pl-2 text-[10.5px] text-slate-400">
          {cmp.test === "insufficient_data" ? "insufficient" : "—"}
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
  const color = barColorHex(cmp);
  return (
    <div className="relative h-full w-full">
      <ForestGrid domain={domain} ticks={ticks} />
      <div
        className="absolute top-1/2 h-[7px] -translate-y-1/2 rounded-full"
        style={{ left: `${left}%`, width: `${width}%`, backgroundColor: color.bar }}
      />
      {!loClamped ? (
        <div
          className="absolute top-1/2 h-[11px] w-[2px] -translate-x-1/2 -translate-y-1/2 rounded"
          style={{ left: `${left}%`, backgroundColor: color.cap }}
        />
      ) : null}
      {!hiClamped ? (
        <div
          className="absolute top-1/2 h-[11px] w-[2px] -translate-x-1/2 -translate-y-1/2 rounded"
          style={{ left: `${right}%`, backgroundColor: color.cap }}
        />
      ) : null}
      <div
        className="absolute top-1/2 h-[12px] w-[3px] -translate-x-1/2 -translate-y-1/2 rounded"
        style={{ left: `${center}%`, backgroundColor: color.tick }}
      />
    </div>
  );
}

function ForestGrid({ domain, ticks }: { domain: number; ticks: number[] }) {
  return (
    <>
      {ticks.map((tick, i) => (
        <div
          key={i}
          className="absolute inset-y-0 w-px"
          style={{
            left: `${valueToPct(tick, domain)}%`,
            backgroundColor: tick === 0 ? "#64748b" : "#e2e8f0",
          }}
        />
      ))}
    </>
  );
}

/** Effects table — same columns as Analysis → Effect explorer. */
function EffectsTable({ analysis }: { analysis: ExperimentAnalysis }) {
  const { t } = useI18n();
  return (
    <table className="w-full border-collapse text-[12px]">
      <thead>
        <Tr head>
          <Th>{t("experiments.explore.col.metric")}</Th>
          <Th>{t("experiments.explore.col.type")}</Th>
          <Th>{t("experiments.explore.col.arm")}</Th>
          <Th align="right">{t("experiments.explore.col.absolute")}</Th>
          <Th align="right">{t("experiments.explore.col.relative")}</Th>
          <Th align="right">p</Th>
          <Th align="center">{t("experiments.explore.col.sig")}</Th>
        </Tr>
      </thead>
      <tbody>
        {analysis.comparisons.map((cmp, i) => (
          <Tr key={`${cmp.metricKey}-${cmp.cellId}-${i}`} zebra={i % 2 === 1}>
            <Td>
              <span className="font-medium text-slate-800">{humanize(cmp.metricKey)}</span>
              {(() => {
                const desc = translateMetricDescription(t, cmp.metricKey);
                return desc ? (
                  <span className="mt-0.5 block max-w-[240px] text-[10px] font-normal leading-snug text-slate-400">
                    {desc}
                  </span>
                ) : null;
              })()}
            </Td>
            <Td>
              <span className="text-slate-500">{reportScaleBadge(t, cmp)}</span>
            </Td>
            <Td>{shortArmLabel(cmp.arm ?? cmp.cellId ?? "")}</Td>
            <Td align="right">
              <span className="tabular-nums font-medium text-slate-800">
                {absoluteEffectText(cmp)}
              </span>
            </Td>
            <Td align="right">
              <span className="tabular-nums text-slate-600">{relativeEffectText(cmp)}</span>
            </Td>
            <Td align="right">{fmtP(cmp.pValue)}</Td>
            <Td align="center">
              {cmp.significant ? (
                <span className="inline-flex rounded-md bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                  {t("experiments.explore.yes")}
                </span>
              ) : (
                <span className="text-slate-400">{t("experiments.explore.no")}</span>
              )}
            </Td>
          </Tr>
        ))}
      </tbody>
    </table>
  );
}

function SliceTable({ slices }: { slices: ExperimentPersonaSlices }) {
  const { t } = useI18n();
  return (
    <table className="w-full border-collapse text-[11.5px]">
      <thead>
        <Tr head>
          <Th>{humanize(slices.dimension)}</Th>
          <Th>{t("experiments.explore.col.arm")}</Th>
          <Th align="right">n</Th>
          <Th align="right">{t("experiments.explore.col.absolute")}</Th>
          <Th align="right">{t("experiments.explore.col.relative")}</Th>
          <Th align="right">p</Th>
          <Th align="center">{t("experiments.explore.col.sig")}</Th>
        </Tr>
      </thead>
      <tbody>
        {slices.rows.map((row, i) => {
          const asCmp = row as unknown as ExperimentComparison;
          return (
            <Tr key={`${row.cellId}-${row.value}-${i}`} zebra={i % 2 === 1}>
              <Td>
                <span className="font-medium text-slate-800">{row.value}</span>
              </Td>
              <Td>{shortArmLabel(row.arm || row.cellId || "")}</Td>
              <Td align="right">
                <span className="tabular-nums text-slate-500">
                  {row.nBaseline}/{row.nTreatment}
                </span>
              </Td>
              <Td align="right">
                <span className="tabular-nums">{absoluteEffectText(asCmp)}</span>
              </Td>
              <Td align="right">
                <span className="tabular-nums text-slate-600">{relativeEffectText(asCmp)}</span>
              </Td>
              <Td align="right">{fmtP(row.pValue)}</Td>
              <Td align="center">
                {row.significant ? (
                  <span className="inline-flex rounded-md bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                    {t("experiments.explore.yes")}
                  </span>
                ) : (
                  <span className="text-slate-400">{t("experiments.explore.no")}</span>
                )}
              </Td>
            </Tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Ranked driver cards — mirrors Analysis → Heterogeneity drivers UI. */
function HeterogeneityDrivers({ analysis }: { analysis: ExperimentAnalysis }) {
  const { t } = useI18n();
  const byArm = new Map<string, ExperimentSliceDriver[]>();
  for (const d of analysis.sliceDrivers ?? []) {
    const key = d.cellId || d.arm || "arm";
    if (!byArm.has(key)) byArm.set(key, []);
    byArm.get(key)!.push(d);
  }

  return (
    <div className="space-y-4">
      {[...byArm.entries()].map(([armKey, drivers]) => {
        const label = shortArmLabel(drivers[0]?.arm || armKey);
        const top = drivers.slice(0, 8);
        return (
          <div key={armKey} className="break-inside-avoid">
            {byArm.size > 1 ? (
              <div className="mb-2">
                <span className="inline-flex rounded-md bg-slate-800 px-2.5 py-1 text-[11px] font-semibold text-white">
                  {label}
                </span>
              </div>
            ) : null}
            <div className="space-y-2">
              {top.map((driver, idx) => (
                <div
                  key={`${driver.dimension}-${idx}`}
                  className="rounded-lg border border-slate-200 bg-slate-50/40 px-3 py-2.5"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[10.5px] font-semibold uppercase tracking-wide text-slate-400">
                      #{idx + 1}
                    </span>
                    <span className="text-[13px] font-semibold text-slate-900">
                      {humanize(driver.dimension)}
                    </span>
                    <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[10.5px] font-medium text-slate-600">
                      {formatDriverDiff(driver.spread, driver.scale)}
                    </span>
                  </div>
                  <p className="mt-1 text-[12.5px] text-slate-600">
                    <span className="font-medium text-emerald-700">{driver.highest.value}</span>{" "}
                    {formatDriverDiff(driver.highest.diff, driver.scale)}
                    {driver.highest.significant ? ` · ${t("experiments.explore.sig")}` : ""}
                    {" · "}
                    <span className="font-medium text-rose-700">{driver.lowest.value}</span>{" "}
                    {formatDriverDiff(driver.lowest.diff, driver.scale)}
                    {driver.lowest.significant ? ` · ${t("experiments.explore.sig")}` : ""}
                  </p>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function formatDriverDiff(diff: number, scale?: string): string {
  const sign = diff >= 0 ? "+" : "";
  const s = (scale || "").toLowerCase();
  if (s === "binary") return `${sign}${(diff * 100).toFixed(1)} pp`;
  if (s === "score") return `${sign}${diff.toFixed(2)} pts`;
  if (s === "count") return `${sign}${diff.toFixed(2)}`;
  return `${sign}${diff.toFixed(2)}`;
}

function absoluteEffectText(cmp: ExperimentComparison): string {
  if (cmp.kind === "categorical" && typeof cmp.effect?.cramersV === "number") {
    return `Cramér V=${cmp.effect.cramersV.toFixed(2)}`;
  }
  if (cmp.kind !== "numerical" || typeof cmp.effect?.diff !== "number") return "—";
  const scale = resolveScale(cmp);
  const d = cmp.effect.diff;
  const sign = d >= 0 ? "+" : "";
  if (scale === "binary") return `${sign}${(d * 100).toFixed(1)} pp`;
  if (scale === "score") return `${sign}${d.toFixed(2)} pts`;
  if (scale === "count") return `${sign}${d.toFixed(2)} count`;
  return `${sign}${d.toFixed(3)}`;
}

function relativeEffectText(cmp: ExperimentComparison): string {
  if (cmp.kind !== "numerical") return "—";
  if (typeof cmp.effect?.deltaPct !== "number") return "—";
  const d = cmp.effect.deltaPct;
  return `${d >= 0 ? "+" : ""}${d.toFixed(1)}% rel`;
}

function resolveScale(cmp: ExperimentComparison): string {
  const s = (cmp.scale || "").toLowerCase();
  if (s === "binary" || s === "score" || s === "count") return s;
  return "numerical";
}

function reportScaleBadge(
  t: (key: MessageKey) => string,
  cmp: ExperimentComparison,
): string {
  if (cmp.kind === "categorical") return t("experiments.explore.badge.cat");
  if (cmp.kind === "textual") return t("experiments.explore.badge.text");
  switch (resolveScale(cmp)) {
    case "binary":
      return t("experiments.explore.badge.rate");
    case "score":
      return t("experiments.explore.badge.score");
    case "count":
      return t("experiments.explore.badge.count");
    default:
      return t("experiments.explore.badge.num");
  }
}

// ---------------------------------------------------------------------------
// Small presentational atoms
// ---------------------------------------------------------------------------

function ReportSection({
  title,
  n,
  children,
}: {
  title: string;
  n: number;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-7 break-inside-avoid">
      <h2 className="mb-2.5 flex items-center gap-2 border-b border-slate-300 pb-1.5 text-[15px] font-semibold text-slate-900">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-slate-900 text-[11px] font-bold text-white">
          {n}
        </span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function SubTitle({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-slate-500 ${className}`}
    >
      {children}
    </div>
  );
}

function ContractRow({ label, items }: { label: string; items?: string[] }) {
  return (
    <div className="flex gap-2 text-[12px]">
      <span className="w-20 shrink-0 text-slate-400">{label}</span>
      <span className="text-slate-700">
        {items && items.length > 0 ? items.map(humanize).join(" · ") : "—"}
      </span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-[12px] text-slate-500">{children}</p>;
}

function Tr({
  children,
  head,
  zebra,
}: {
  children: React.ReactNode;
  head?: boolean;
  zebra?: boolean;
}) {
  const cls = head
    ? "border-b border-slate-300"
    : `border-b border-slate-100 ${zebra ? "bg-slate-50/60" : ""}`;
  return <tr className={cls}>{children}</tr>;
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
}) {
  return (
    <th
      className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400"
      style={{ textAlign: align }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
  mono,
  strong,
  className = "",
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  mono?: boolean;
  strong?: boolean;
  className?: string;
}) {
  return (
    <td
      className={`px-2 py-1.5 text-slate-700 ${mono ? "font-mono text-[10.5px]" : ""} ${
        strong ? "font-semibold text-slate-900" : ""
      } ${className}`}
      style={{ textAlign: align }}
    >
      {children}
    </td>
  );
}

// ---------------------------------------------------------------------------
// Data helpers (self-contained mirror of the Scorecard's formatting)
// ---------------------------------------------------------------------------

interface ReportArm {
  key: string;
  label: string;
  value?: string | null;
  n?: number | null;
  pool?: string | null;
  baseline?: boolean;
}

function reportArms(manifest: ExperimentManifest): ReportArm[] {
  const arms = manifest.sampling.arms;
  if (arms && arms.length > 0) {
    return arms.map((a) => ({
      key: a.cellId,
      label: shortArmLabel(a.label || a.cellId),
      value: a.dimensionValue ?? null,
      n: a.personaCount ?? null,
      pool: a.personaPool ?? null,
      baseline: false,
    }));
  }
  return (manifest.cells ?? []).map((c) => ({
    key: c.cellId,
    label: shortArmLabel(c.arm || c.cellId),
    value: c.dimensionValue ?? null,
    n: c.personaCount ?? null,
    pool: c.personaPool ?? null,
    baseline: Boolean(c.baseline),
  }));
}

function cohortSummary(manifest: ExperimentManifest): string {
  const top = manifest.sampling.personaPool;
  if (top) return poolSlug(top);
  const pools = [
    ...new Set(
      (manifest.sampling.arms ?? [])
        .map((a) => a.personaPool)
        .filter((p): p is string => Boolean(p)),
    ),
  ];
  if (pools.length === 0) return "—";
  if (pools.length === 1) return poolSlug(pools[0]);
  return `synthesized · ${pools.length} cohorts`;
}

function poolSlug(pool?: string | null): string {
  if (!pool) return "—";
  return pool.split("/").filter(Boolean).pop() || pool;
}

const ROLE_SECTIONS = [
  { role: "primary", label: "Primary" },
  { role: "secondary", label: "Secondary" },
  { role: "guardrail", label: "Guardrail" },
];

function reportRoleLabel(t: (key: MessageKey) => string, role: string): string {
  if (role === "primary") return t("experiments.report.role.primary");
  if (role === "guardrail") return t("experiments.report.role.guardrail");
  return t("experiments.report.role.secondary");
}

function groupByRole(comparisons: ExperimentComparison[]) {
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

function shortArmLabel(label: string): string {
  const s = (label ?? "").trim();
  const eq = s.lastIndexOf("=");
  if (eq > 0 && eq < s.length - 1 && !s.includes(" · ")) {
    return s.slice(eq + 1).trim() || s;
  }
  return s;
}

function humanize(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function deltaText(cmp: ExperimentComparison): string {
  if (typeof cmp.effect?.deltaPct === "number") {
    const d = cmp.effect.deltaPct;
    return `${d >= 0 ? "+" : ""}${d.toFixed(1)}%`;
  }
  if (typeof cmp.effect?.diff === "number") {
    const d = cmp.effect.diff;
    return `${d >= 0 ? "+" : ""}${d.toFixed(2)}`;
  }
  return "—";
}

/** Forest-plot symmetric axis domain (±%) rounded to a clean tick. */
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

/** "±X.X%" from the CI half-width when available, else the adjusted p-value. */
function marginOrP(cmp: ExperimentComparison): string {
  const ci = cmp.effect?.ciPct;
  if (cmp.kind === "numerical" && ci && typeof cmp.effect?.deltaPct === "number") {
    const margin = Math.abs(ci[1] - ci[0]) / 2;
    if (Number.isFinite(margin) && margin > 0) return `±${margin.toFixed(1)}%`;
  }
  return pText(cmp);
}

// Print-safe hex palettes (theme tokens don't survive print / white paper).
const CAT_HEX = [
  "#0ea5e9",
  "#8b5cf6",
  "#10b981",
  "#f59e0b",
  "#f43f5e",
  "#06b6d4",
  "#d946ef",
  "#84cc16",
  "#6366f1",
  "#14b8a6",
];

const catHex = (i: number) => CAT_HEX[i % CAT_HEX.length];

function barColorHex(cmp: ExperimentComparison): { bar: string; cap: string; tick: string } {
  if (!cmp.significant) return { bar: "#cbd5e1", cap: "#94a3b8", tick: "#334155" };
  const diff = cmp.effect?.diff ?? cmp.effect?.deltaPct ?? 0;
  return diff < 0
    ? { bar: "#fca5a5", cap: "#dc2626", tick: "#b91c1c" }
    : { bar: "#6ee7b7", cap: "#059669", tick: "#047857" };
}

function insufficientText(cmp: ExperimentComparison): string {
  if (cmp.test === "skipped") return "textual (not tested)";
  switch (cmp.reason) {
    case "too_few_responses":
      return "too few responses";
    case "single_category":
      return "only one option";
    default:
      return "insufficient";
  }
}

function pText(cmp: ExperimentComparison): string {
  const p = cmp.pValueAdj ?? cmp.pValue;
  if (typeof p !== "number") return "";
  return p < 0.001 ? "p<0.001" : `p=${p.toFixed(3)}`;
}

function fmtP(p: number | null | undefined): string {
  if (typeof p !== "number") return "—";
  return p < 0.001 ? "<0.001" : p.toFixed(3);
}

function correctionLabel(method: string | undefined): string {
  if (!method) return "correction";
  const m = method.toLowerCase();
  if (m.includes("bh") || m.includes("benjamini")) return "BH";
  if (m.includes("bonferroni")) return "Bonferroni";
  if (m === "none") return "no correction";
  return method;
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}
