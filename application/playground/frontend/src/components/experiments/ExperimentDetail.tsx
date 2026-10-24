import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useI18n } from "@/i18n/I18nProvider";
import type {
  ExperimentAnalysis,
  ExperimentCell,
  ExperimentCohortMix,
  ExperimentCohortStrategy,
  ExperimentFactor,
  ExperimentManifest,
} from "@/lib/types";
import {
  cuaRuntimeLabel,
  webPersonaAgentLabel,
} from "@/lib/personaAgentCatalog";
import {
  downloadExperimentCsv,
  downloadExperimentJson,
} from "@/lib/experimentExport";
import { FOCUS_RING, Sym, humanizeToken } from "../cockpit/cockpitShared";
import { Markdown } from "../Markdown";
import { StudioGlassPanel } from "../studio/StudioShell";
import { ExperimentExplorePanel } from "./ExperimentExplorePanel";
import { ExperimentReportOverlay } from "./ExperimentReport";
import { ExperimentScorecard } from "./ExperimentScorecard";
import {
  AxisBadge,
  MetaChip,
  MetricContractSummary,
  SectionHeader,
  StatusChip,
  errMessage,
} from "./experimentShared";

export interface ExperimentDetailProps {
  experimentId: string;
  onOpenJob: (jobName: string) => void;
}

type DetailPanel = "setup" | "results" | "analysis";

/** Shared with ExplorePanel default fetch so Results prefetch warms Analysis + Export. */
export function experimentSlicesQueryKey(
  experimentId: string,
  confidence: number,
  fdr: boolean,
) {
  return ["experiment-analysis-explore", experimentId, confidence, fdr, null, null] as const;
}

export function ExperimentDetail({ experimentId, onOpenJob }: ExperimentDetailProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const detailQuery = useQuery<ExperimentManifest>({
    queryKey: ["experiment", experimentId],
    queryFn: () => api.getExperiment(experimentId),
    refetchInterval: (q) => (q.state.data?.status === "complete" ? false : 3000),
  });

  const completed = detailQuery.data?.progress?.completedTrials ?? 0;
  const isComplete = detailQuery.data?.status === "complete";
  const [panel, setPanel] = useState<DetailPanel | null>(null);
  const panelTouched = useRef(false);
  const [confidence, setConfidence] = useState(0.95);
  const [fdr, setFdr] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [exportBusy, setExportBusy] = useState<"json" | "csv" | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const exportBtnRef = useRef<HTMLButtonElement>(null);
  const [exportPos, setExportPos] = useState<{ top: number; right: number }>({ top: 0, right: 0 });

  const openExport = () => {
    if (exportBtnRef.current) {
      const r = exportBtnRef.current.getBoundingClientRect();
      setExportPos({ top: r.bottom + 4, right: window.innerWidth - r.right });
    }
    setExportOpen(true);
  };

  // New experiment id → re-apply status-based default.
  useEffect(() => {
    panelTouched.current = false;
    setPanel(null);
  }, [experimentId]);

  const analysisQuery = useQuery<ExperimentAnalysis>({
    queryKey: ["experiment-analysis", experimentId, confidence, fdr],
    queryFn: () => api.getExperimentAnalysis(experimentId, confidence, fdr),
    enabled: completed > 0,
    refetchInterval: isComplete ? false : 5000,
    staleTime: 60_000,
  });

  // Prefetch full (slices) analysis as soon as trials exist so Export / PDF /
  // Analysis never hand the operator an incomplete payload.
  const slicesQuery = useQuery<ExperimentAnalysis>({
    queryKey: experimentSlicesQueryKey(experimentId, confidence, fdr),
    queryFn: () =>
      api.getExperimentAnalysis(experimentId, confidence, fdr, {
        includeSlices: true,
      }),
    enabled: completed > 0,
    staleTime: 60_000,
  });

  const ensureFullAnalysis = async (): Promise<ExperimentAnalysis | null> => {
    try {
      return await queryClient.fetchQuery({
        queryKey: experimentSlicesQueryKey(experimentId, confidence, fdr),
        queryFn: () =>
          api.getExperimentAnalysis(experimentId, confidence, fdr, {
            includeSlices: true,
          }),
        staleTime: 60_000,
      });
    } catch {
      return analysisQuery.data ?? null;
    }
  };

  // Default to Results (live progress while running, final once complete) so a
  // launched run lands on its outcome; the operator can still switch to Setup.
  useEffect(() => {
    if (panelTouched.current || !detailQuery.data) return;
    setPanel("results");
  }, [detailQuery.data, detailQuery.data?.status]);

  const activePanel: DetailPanel = panel ?? "results";

  const selectPanel = (next: DetailPanel) => {
    panelTouched.current = true;
    setPanel(next);
  };

  if (detailQuery.isLoading) {
    return <p className="text-[13px] text-text-dim">{t("experiments.detail.loading")}</p>;
  }
  if (detailQuery.isError || !detailQuery.data) {
    return (
      <p className="rounded-md bg-danger/10 p-3 text-[13px] text-danger" role="alert">
        {errMessage(detailQuery.error)}
      </p>
    );
  }

  const manifest = detailQuery.data;
  const axis = manifest.axis ?? "sut";
  const progress = manifest.progress ?? { trialCount: 0, completedTrials: 0 };
  const pct =
    progress.trialCount > 0
      ? Math.round((progress.completedTrials / progress.trialCount) * 100)
      : 0;
  const live = !isComplete && completed > 0;
  const canExport = completed > 0;

  return (
    <div className="space-y-4">
      <StudioGlassPanel className="overflow-visible p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-display text-[16px] font-semibold text-text-main">
              {manifest.name || manifest.experimentId}
            </h2>
            <div className="font-mono text-[11.5px] text-text-dim">{manifest.task}</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1 rounded-lg p-0.5 glass-tile">
              <PanelTab
                label={t("experiments.detail.tabSetup")}
                active={activePanel === "setup"}
                onClick={() => selectPanel("setup")}
              />
              <PanelTab
                label={t("experiments.detail.tabResults")}
                active={activePanel === "results"}
                onClick={() => selectPanel("results")}
              />
              <PanelTab
                label={t("experiments.detail.tabAnalysis")}
                active={activePanel === "analysis"}
                onClick={() => selectPanel("analysis")}
              />
            </div>
            <div className="relative">
              <button
                ref={exportBtnRef}
                type="button"
                disabled={!canExport}
                title={canExport ? t("experiments.detail.exportReport") : t("experiments.detail.exportUnavailable")}
                onClick={() => exportOpen ? setExportOpen(false) : openExport()}
                className={`inline-flex items-center gap-1.5 rounded-md border border-outline/50 bg-surface/40 px-2.5 py-1 text-[12px] font-medium text-text-variant transition hover:border-outline hover:text-text-main disabled:cursor-not-allowed disabled:opacity-45 ${FOCUS_RING}`}
              >
                <Sym name="download" size={14} />
                {t("experiments.detail.export")}
                <Sym name="expand_more" size={14} className="opacity-70" />
              </button>
              {exportOpen ? createPortal(
                <>
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setExportOpen(false)}
                  />
                  <div
                    className="pop-in fixed z-50 w-56 overflow-hidden rounded-lg border border-outline/50 bg-surface shadow-xl"
                    style={{ top: exportPos.top, right: exportPos.right }}
                  >
                    <ExportMenuItem
                      icon="picture_as_pdf"
                      title={t("experiments.detail.reportPdfTitle")}
                      hint={
                        slicesQuery.isFetched
                          ? t("experiments.detail.reportPdfHint")
                          : t("experiments.detail.reportPdfHintPreparing")
                      }
                      onClick={() => {
                        setExportOpen(false);
                        setShowReport(true);
                      }}
                    />
                    <ExportMenuItem
                      icon="data_object"
                      title={t("experiments.detail.dataJsonTitle")}
                      hint={
                        exportBusy === "json"
                          ? t("experiments.detail.exportPreparing")
                          : t("experiments.detail.dataJsonHint")
                      }
                      onClick={() => {
                        setExportOpen(false);
                        void (async () => {
                          setExportBusy("json");
                          try {
                            const withSlices = await ensureFullAnalysis();
                            downloadExperimentJson(manifest, withSlices);
                          } finally {
                            setExportBusy(null);
                          }
                        })();
                      }}
                    />
                    <ExportMenuItem
                      icon="table_view"
                      title={t("experiments.detail.dataCsvTitle")}
                      hint={
                        exportBusy === "csv"
                          ? t("experiments.detail.exportPreparing")
                          : t("experiments.detail.dataCsvHint")
                      }
                      onClick={() => {
                        setExportOpen(false);
                        void (async () => {
                          setExportBusy("csv");
                          try {
                            // CSV is the scorecard comparisons; still wait for
                            // full analysis so arm sizes / paired tests match UI.
                            const withSlices = await ensureFullAnalysis();
                            downloadExperimentCsv(
                              manifest,
                              withSlices ?? analysisQuery.data ?? null,
                            );
                          } finally {
                            setExportBusy(null);
                          }
                        })();
                      }}
                    />
                  </div>
                </>,
                document.body
              ) : null}
            </div>
            <StatusChip status={manifest.status} />
          </div>
        </div>

        {activePanel === "setup" ? (
          <>
            {manifest.hypothesis ? (
              <div className="mb-3 flex gap-2 rounded-lg border border-primary/25 bg-primary/[0.06] p-2.5">
                <Sym name="lightbulb" size={15} className="mt-0.5 shrink-0 text-primary" />
                <p className="text-[12.5px] leading-snug text-text-variant">
                  <span className="font-semibold text-text-main">{t("experiments.detail.hypothesis")} </span>
                  {manifest.hypothesis}
                </p>
              </div>
            ) : null}
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              <AxisBadge axis={axis} />
              <MetaChip>{manifest.design.effectiveType.replace("_", " ")}</MetaChip>
              <MetaChip>{t("experiments.detail.arms", { count: manifest.cells.length })}</MetaChip>
              <MetaChip>{samplingLabel(manifest)}</MetaChip>
            </div>
            <MetricContractSummary contract={manifest.metricContract} />
          </>
        ) : activePanel === "results" ? (
          <>
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              <AxisBadge axis={axis} />
              <MetaChip>{manifest.design.effectiveType.replace("_", " ")}</MetaChip>
              <MetaChip>{t("experiments.detail.arms", { count: manifest.cells.length })}</MetaChip>
              <MetaChip>
                {t("experiments.detail.trials", {
                  completed: progress.completedTrials,
                  total: progress.trialCount,
                })}
              </MetaChip>
            </div>
            {!isComplete ? (
              <ArmProgressBars cells={manifest.cells} overallPct={pct} />
            ) : null}
            <RunMetaStrip manifest={manifest} />
            <MetricContractSummary contract={manifest.metricContract} />
          </>
        ) : (
          <>
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              <AxisBadge axis={axis} />
              <MetaChip>{t("experiments.detail.arms", { count: manifest.cells.length })}</MetaChip>
              <MetaChip>
                {t("experiments.detail.trials", {
                  completed: progress.completedTrials,
                  total: progress.trialCount,
                })}
              </MetaChip>
            </div>
          </>
        )}
      </StudioGlassPanel>

      {activePanel === "results" ? (
        <>
          <ExperimentScorecard
            analysis={analysisQuery.data}
            loading={analysisQuery.isLoading}
            pending={completed === 0}
            live={live}
            confidence={confidence}
            onConfidenceChange={setConfidence}
            fdr={fdr}
            onFdrChange={setFdr}
          />
        </>
      ) : null}

      {activePanel === "analysis" ? (
        <ExperimentExplorePanel
          experimentId={experimentId}
          manifest={manifest}
          confidence={confidence}
          fdr={fdr}
          pending={completed === 0}
        />
      ) : null}

      {activePanel === "setup" ? (
        <div className="space-y-4">
          <DesignVariablesPanel
            factors={manifest.factors}
            cells={manifest.cells}
            axis={axis}
            putDimension={manifest.design.putDimension ?? manifest.sampling.dimension}
          />
          {manifest.instructionMarkdown?.trim() ? (
            <StudioGlassPanel className="p-4">
              <InstructionBlock markdown={manifest.instructionMarkdown} />
            </StudioGlassPanel>
          ) : null}
          <CohortContractPanel strategy={manifest.cohortStrategy} />
          <StudioGlassPanel className="p-4">
          <SectionHeader
            icon="conversion_path"
            title={t("experiments.detail.thisRun")}
            right={
              <RunVsContractChip
                strategy={manifest.cohortStrategy}
                runN={runCohortSize(manifest)}
                mix={manifest.cohortMix}
              />
            }
          />
          <RunConfigStrip manifest={manifest} strategy={manifest.cohortStrategy} />
          <RunCohortMixPanel mix={manifest.cohortMix} />
          <RunArmsTable manifest={manifest} onOpenJob={onOpenJob} />
        </StudioGlassPanel>
        </div>
      ) : null}

      <ExperimentReportOverlay
        manifest={manifest}
        analysis={slicesQuery.data ?? analysisQuery.data ?? null}
        analysisLoading={showReport && !slicesQuery.isFetched}
        open={showReport}
        onClose={() => setShowReport(false)}
      />
    </div>
  );
}

/** One action row in the Export dropdown (Report / Data). */
function ExportMenuItem({
  icon,
  title,
  hint,
  onClick,
}: {
  icon: string;
  title: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-start gap-2.5 px-3 py-2 text-left transition hover:bg-surface-high/70 ${FOCUS_RING}`}
    >
      <Sym name={icon} size={16} className="mt-0.5 text-text-dim" />
      <span>
        <span className="block text-[12.5px] font-medium text-text-main">{title}</span>
        <span className="block text-[11px] text-text-dim">{hint}</span>
      </span>
    </button>
  );
}

/** Prefer the expanded arm string; strip "Factor=Level" → "Level" when single. */
function cellArmLabel(cell: ExperimentCell): string {
  const raw =
    (cell.arm && cell.arm.trim()) ||
    Object.values(cell.factorLevels ?? {}).filter(Boolean).join(" · ") ||
    cell.cellId;
  const eq = raw.lastIndexOf("=");
  if (eq > 0 && eq < raw.length - 1 && !raw.includes(" · ")) {
    return raw.slice(eq + 1).trim() || raw;
  }
  return raw;
}

function RunArmsTable({
  manifest,
  onOpenJob,
}: {
  manifest: ExperimentManifest;
  onOpenJob: (jobName: string) => void;
}) {
  const { t } = useI18n();
  const axis = manifest.axis ?? "sut";
  const put = axis === "put";
  const dim =
    manifest.sampling.dimension ?? manifest.design.putDimension ?? "persona";
  const sharedN =
    manifest.sampling.personaIds?.length ??
    (typeof manifest.sampling.perArm === "number" ? manifest.sampling.perArm : null);

  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b border-outline/40 text-left text-[11px] uppercase tracking-wide text-text-dim">
            <th className="py-2 pr-3 font-medium">{t("experiments.detail.colArm")}</th>
            {put ? <th className="py-2 pr-3 font-medium">{t("experiments.detail.colGroup")}</th> : null}
            {put ? <th className="py-2 pr-3 font-medium">n</th> : null}
            <th className="py-2 pr-3 font-medium">{t("experiments.detail.colTrials")}</th>
            <th className="py-2 pr-3 font-medium">{t("experiments.detail.colCost")}</th>
            <th className="py-2 pr-3 font-medium">{t("experiments.detail.colStatus")}</th>
            <th className="py-2 font-medium">{t("experiments.detail.colJob")}</th>
          </tr>
        </thead>
        <tbody>
          {manifest.cells.map((cell) => (
            <tr key={cell.cellId} className="border-b border-outline/15">
              <td className="py-2 pr-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  {cell.baseline ? <MetaChip tone="primary">{t("experiments.detail.control")}</MetaChip> : null}
                  <span className="font-semibold text-text-main">{cellArmLabel(cell)}</span>
                </div>
              </td>
              {put ? (
                <td className="py-2 pr-3 text-text-variant">
                  {humanizeToken(dim)} = {cell.dimensionValue || cell.arm || "—"}
                </td>
              ) : null}
              {put ? (
                <td className="py-2 pr-3 tabular-nums text-text-variant">
                  {cell.personaCount ?? "—"}
                </td>
              ) : null}
              <td className="py-2 pr-3 text-text-variant">
                {cell.coverage
                  ? `${cell.coverage.completedTrials}/${cell.coverage.trialCount}`
                  : sharedN != null && !put
                    ? `—/${sharedN}`
                    : "—"}
              </td>
              <td className="py-2 pr-3 tabular-nums text-text-variant">
                {typeof cell.coverage?.costUsd === "number"
                  ? `$${cell.coverage.costUsd.toFixed(3)}`
                  : "—"}
              </td>
              <td className="py-2 pr-3">
                <StatusChip status={cell.status} />
              </td>
              <td className="py-2">
                {cell.jobName ? (
                  <button
                    type="button"
                    onClick={() => onOpenJob(cell.jobName!)}
                    title={t("experiments.detail.openArmJob")}
                    className={`inline-flex items-center gap-1 font-mono text-[11px] text-primary hover:text-primary-dim hover:underline ${FOCUS_RING}`}
                  >
                    <Sym name="open_in_new" size={13} />
                    {cell.jobName}
                  </button>
                ) : (
                  <span className="font-mono text-[11px] text-text-dim">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!put ? (
        <p className="mt-1.5 text-[11.5px] text-text-dim">{t("experiments.detail.sharedCohort")}</p>
      ) : null}
    </div>
  );
}

function DesignVariablesPanel({
  factors,
  cells,
  axis,
  putDimension,
}: {
  factors?: ExperimentFactor[] | null;
  cells: ExperimentCell[];
  axis: string;
  putDimension?: string | null;
}) {
  const { t } = useI18n();
  const list = factors ?? [];

  if (axis === "put") {
    const dim = putDimension || "persona attribute";
    const groups = cells.map((c) => c.dimensionValue || c.arm || c.cellId);
    const control = cells.find((c) => c.baseline);
    const controlKey = control?.dimensionValue || control?.arm;
    return (
      <StudioGlassPanel className="p-4">
        <SectionHeader
          icon="tune"
          title={t("experiments.detail.variables")}
          hint={`${humanizeToken(dim)} · ${t("experiments.detail.fixedEnvironment")}`}
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {groups.map((g) => (
            <MetaChip key={g} tone={g === controlKey ? "primary" : "neutral"}>
              {g === controlKey ? `${t("experiments.detail.control")} · ` : ""}
              {g}
            </MetaChip>
          ))}
        </div>
      </StudioGlassPanel>
    );
  }

  if (list.length === 0) {
    return (
      <StudioGlassPanel className="p-4">
        <SectionHeader icon="tune" title={t("experiments.detail.variables")} />
        {cells.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {cells.map((c) => (
              <MetaChip key={c.cellId} tone={c.baseline ? "primary" : "neutral"}>
                {c.baseline ? `${t("experiments.detail.control")} · ` : ""}
                {cellArmLabel(c)}
              </MetaChip>
            ))}
          </div>
        ) : (
          <p className="mt-2 text-[12.5px] text-text-dim">{t("experiments.detail.noVariables")}</p>
        )}
      </StudioGlassPanel>
    );
  }

  return (
    <StudioGlassPanel className="p-4">
      <SectionHeader
        icon="tune"
        title={t("experiments.detail.variables")}
        hint={t("experiments.detail.variablesHint", {
          factors: list.length,
          arms: cells.length,
        })}
      />
      <div className="mt-2 space-y-2.5">
        {list.map((f) => (
          <div
            key={f.id}
            className="rounded-lg border border-outline/30 bg-surface/40 px-3 py-2.5"
          >
            <div className="mb-1.5 text-[13px] font-semibold text-text-main">
              {f.label || humanizeToken(f.id)}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {f.levels.map((lv) => (
                <span
                  key={lv.id}
                  className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[12px] ${
                    lv.baseline
                      ? "border-primary/45 bg-primary/10 text-primary"
                      : "border-outline/40 bg-surface-high/50 text-text-variant"
                  }`}
                >
                  {lv.baseline ? <Sym name="flag" size={12} /> : null}
                  {lv.label || lv.id}
                  {lv.baseline ? (
                    <span className="text-[10px] font-medium uppercase tracking-wide opacity-80">
                      {t("experiments.detail.control")}
                    </span>
                  ) : null}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </StudioGlassPanel>
  );
}

function PanelTab({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-md px-3 py-1 text-[12.5px] font-medium transition ${FOCUS_RING} ${
        active ? "bg-primary text-on-primary" : "text-text-variant hover:text-text-main"
      }`}
    >
      {label}
    </button>
  );
}

/** Per-arm live progress: one bar per cohort/arm instead of a single total. */
function ArmProgressBars({
  cells,
  overallPct,
}: {
  cells: ExperimentCell[];
  overallPct: number;
}) {
  const { t } = useI18n();
  if (!cells || cells.length <= 1) {
    return (
      <div className="mb-2 h-2 w-full overflow-hidden rounded-full bg-surface-high/60">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${overallPct}%` }}
        />
      </div>
    );
  }
  return (
    <div className="mb-2 space-y-1.5">
      {cells.map((cell, i) => {
        const label =
          Object.values(cell.factorLevels ?? {}).join(" · ") ||
          cell.arm ||
          t("experiments.detail.armN", { n: i + 1 });
        const total = cell.coverage?.trialCount ?? 0;
        const done = cell.coverage?.completedTrials ?? 0;
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        const finished = total > 0 && done >= total;
        return (
          <div key={cell.cellId || cell.jobName || i} className="flex items-center gap-2">
            <span className="flex w-40 shrink-0 items-center gap-1 truncate text-[11.5px] text-text-variant">
              {cell.baseline ? (
                <Sym name="flag" size={11} className="shrink-0 text-text-dim" />
              ) : null}
              <span className="truncate" title={label}>
                {label}
              </span>
            </span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-high/60">
              <div
                className={`h-full rounded-full transition-all ${finished ? "bg-secondary" : "bg-primary"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-12 shrink-0 text-right text-[11px] tabular-nums text-text-dim">
              {done}/{total}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Cohort source for the header: the shared dataset when drawn from one, or
 * "synthesized · N cohorts" when each arm was generated into its own pool
 * (PUT contrast). Falls back to a single per-arm pool when arms share one.
 */
function distinctArmPools(manifest: ExperimentManifest): string[] {
  return [
    ...new Set(
      (manifest.sampling.arms ?? [])
        .map((a) => a.personaPool)
        .filter((p): p is string => Boolean(p)),
    ),
  ];
}

/** True when arms were each synthesized into their own pool (PUT contrast). */
function isSynthesizedPool(manifest: ExperimentManifest): boolean {
  if (manifest.sampling.personaPool) return false;
  return distinctArmPools(manifest).length > 1;
}

function poolSummary(
  manifest: ExperimentManifest,
  t: ReturnType<typeof useI18n>["t"],
): string {
  const top = manifest.sampling.personaPool;
  if (top) return top.split("/").pop() || top;
  const pools = distinctArmPools(manifest);
  if (pools.length === 0) return "—";
  if (pools.length === 1) return pools[0].split("/").pop() || pools[0];
  return t("experiments.detail.synthesizedCohorts", { count: pools.length });
}

function RunMetaStrip({ manifest }: { manifest: ExperimentManifest }) {
  const { t } = useI18n();
  const model = manifest.personaModel?.split("/").pop() || manifest.personaModel;
  const agentLabel = manifest.agentName
    ? webPersonaAgentLabel(manifest.agentName)
    : manifest.cuaBackend
      ? `${t("experiments.detail.computerUse")} · ${cuaRuntimeLabel(manifest.cuaBackend)}`
      : null;
  const items: Array<{ label: string; value: string }> = [
    { label: t("experiments.detail.metaModel"), value: model || "—" },
    ...(agentLabel ? [{ label: t("experiments.detail.metaAgent"), value: agentLabel }] : []),
    {
      label: t("experiments.detail.metaCost"),
      value: typeof manifest.costUsd === "number" ? `$${manifest.costUsd.toFixed(3)}` : "—",
    },
    {
      label: t("experiments.detail.metaDuration"),
      value:
        typeof manifest.durationSeconds === "number"
          ? formatDuration(manifest.durationSeconds)
          : "—",
    },
    { label: t("experiments.detail.metaPool"), value: poolSummary(manifest, t) },
    {
      label: t("experiments.detail.metaCohort"),
      value:
        typeof manifest.sampling.perArm === "number"
          ? `${manifest.sampling.perArm}/arm · seed ${manifest.sampling.seed}`
          : `seed ${manifest.sampling.seed}`,
    },
  ];
  return (
    <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {items.map((item) => (
        <div
          key={item.label}
          className="rounded-md border border-outline/20 bg-surface/40 px-2.5 py-1.5"
        >
          <div className="text-[10.5px] font-medium uppercase tracking-wide text-text-dim">
            {item.label}
          </div>
          <div className="mt-0.5 truncate text-[12.5px] font-medium text-text-main" title={item.value}>
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function contractExpectedN(
  strategy: ExperimentCohortStrategy | null | undefined,
): { n: number | null; label: string } {
  if (!strategy) return { n: null, label: "—" };
  const sampling = strategy.sampling ?? {};
  const filters = strategy.dimensionFilters ?? {};
  const fields =
    (sampling.fields && sampling.fields.length > 0
      ? sampling.fields
      : Object.keys(filters).filter((k) => (filters[k]?.length ?? 0) > 0)) ?? [];
  const allocation = sampling.allocation || "equalTotal";
  const cells = fields.reduce(
    (acc, f) => acc * Math.max(1, (filters[f] ?? []).length),
    1,
  );

  if (allocation === "perCell" && typeof sampling.perCell === "number") {
    const n = cells * sampling.perCell;
    const parts = fields
      .map((f) => `${(filters[f] ?? []).length}×${humanizeToken(f)}`)
      .join(" × ");
    return {
      n,
      label: parts
        ? `${n} personas · ${sampling.perCell}/cell × ${parts}`
        : `${n} personas · ${sampling.perCell}/cell`,
    };
  }
  if (
    allocation === "equalTotal" ||
    allocation === "proportional"
  ) {
    const size = sampling.sampleSize ?? sampling.size;
    if (typeof size === "number") {
      return { n: size, label: `${size} personas · ${allocation}` };
    }
  }
  if (typeof sampling.sampleSize === "number") {
    return { n: sampling.sampleSize, label: `${sampling.sampleSize} personas` };
  }
  return { n: null, label: "size not fixed on contract" };
}

function runCohortSize(manifest: ExperimentManifest): number | null {
  if (manifest.axis === "put") {
    const total = (manifest.sampling.arms ?? []).reduce(
      (sum, a) => sum + (a.personaCount ?? 0),
      0,
    );
    return total > 0 ? total : null;
  }
  return (
    manifest.sampling.personaIds?.length ??
    (typeof manifest.sampling.perArm === "number" ? manifest.sampling.perArm : null)
  );
}

function CohortContractPanel({
  strategy,
}: {
  strategy: ExperimentCohortStrategy | null | undefined;
}) {
  const { t } = useI18n();
  if (!strategy) {
    return (
      <StudioGlassPanel className="p-4">
        <SectionHeader icon="filter_alt" title={t("experiments.detail.cohortContract")} />
        <p className="mt-2 text-[12.5px] text-text-dim">{t("experiments.detail.noCohortContract")}</p>
      </StudioGlassPanel>
    );
  }

  const filters = Object.entries(strategy.dimensionFilters ?? {}).filter(
    ([, values]) => (values?.length ?? 0) > 0,
  );
  const samplingBlock = strategy.sampling ?? {};
  const fields = samplingBlock.fields ?? [];
  const allocation = samplingBlock.allocation || "equalTotal";
  const portions =
    strategy.portions ||
    (samplingBlock.portions as Record<string, Record<string, number>> | undefined) ||
    null;
  const expected = contractExpectedN(strategy);
  const mixChip = portions
    ? t("experiments.detail.mixCustom")
    : allocation === "proportional"
      ? t("experiments.detail.mixProportional")
      : t("experiments.detail.mixEqual");

  return (
    <StudioGlassPanel className="p-4">
      <SectionHeader
        icon="filter_alt"
        title={t("experiments.detail.cohortContract")}
        hint={expected.n != null ? `n=${expected.n}` : undefined}
      />

      <div className="mt-2 flex flex-wrap gap-1.5">
        {samplingBlock.mode ? <MetaChip>{samplingBlock.mode}</MetaChip> : null}
        <MetaChip>{mixChip}</MetaChip>
        {typeof samplingBlock.perCell === "number" ? (
          <MetaChip>{t("experiments.detail.perCell", { count: samplingBlock.perCell })}</MetaChip>
        ) : null}
        {(strategy.sources ?? []).map((s) => (
          <MetaChip key={s}>{t("experiments.detail.source", { name: s })}</MetaChip>
        ))}
      </div>

      <div className="mt-3 space-y-2">
        {filters.length === 0 ? (
          <p className="text-[12.5px] text-text-dim">{t("experiments.detail.noAttributeFilters")}</p>
        ) : (
          filters.map(([dim, values]) => {
            const dimPortions = portions?.[dim];
            const equalShare = values.length > 0 ? 1 / values.length : 0;
            return (
              <div
                key={dim}
                className="rounded-md border border-outline/20 bg-surface/30 px-2.5 py-2"
              >
                <div className="text-[12.5px] font-semibold text-text-main">
                  {humanizeToken(dim)}
                  {fields.includes(dim) ? (
                    <span className="ml-1.5 text-[10.5px] font-medium uppercase tracking-wide text-secondary">
                      {t("experiments.detail.stratify")}
                    </span>
                  ) : null}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {values.map((v) => {
                    const w = dimPortions?.[v];
                    const pct =
                      typeof w === "number"
                        ? `${Math.round(w * 100)}%`
                        : `${Math.round(equalShare * 100)}%`;
                    return (
                      <span
                        key={v}
                        className="inline-flex items-center gap-1 rounded-md bg-surface-high/70 px-2 py-0.5 text-[11.5px] text-text-variant"
                      >
                        <span className="text-text-main">{v}</span>
                        <span className="tabular-nums text-text-dim">{pct}</span>
                      </span>
                    );
                  })}
                </div>
              </div>
            );
          })
        )}
      </div>
    </StudioGlassPanel>
  );
}

function RunConfigStrip({
  manifest,
  strategy,
}: {
  manifest: ExperimentManifest;
  strategy: ExperimentCohortStrategy | null | undefined;
}) {
  const { t } = useI18n();
  const pool = poolSummary(manifest, t);
  const synthesized = isSynthesizedPool(manifest);
  const runN = runCohortSize(manifest);
  const expected = contractExpectedN(strategy);
  const items: Array<{ label: string; value: string }> = [
    {
      label: synthesized
        ? t("experiments.detail.configCohorts")
        : t("experiments.detail.configDataset"),
      value: pool,
    },
    {
      label: t("experiments.detail.thisRunN"),
      value: runN != null ? t("experiments.detail.personasCount", { count: runN }) : "—",
    },
    {
      label: t("experiments.detail.contractN"),
      value: expected.n != null ? String(expected.n) : "—",
    },
    {
      label: t("experiments.detail.seed"),
      value: String(manifest.sampling.seed ?? "—"),
    },
  ];
  const exec = manifest.execution;
  if (exec) {
    items.push({
      label: t("experiments.detail.parallel"),
      value: exec.parallelArms
        ? `${exec.effectiveConcurrent} · ${exec.nConcurrentTrials}×${exec.armCount}`
        : `${exec.effectiveConcurrent} · ${exec.nConcurrentTrials}/arm`,
    });
  }
  return (
    <div className={`grid gap-2 sm:grid-cols-2 ${items.length >= 5 ? "lg:grid-cols-5" : "lg:grid-cols-4"}`}>
      {items.map((item) => (
        <div
          key={item.label}
          className="rounded-md border border-outline/20 bg-surface/40 px-2.5 py-1.5"
        >
          <div className="text-[10.5px] font-medium uppercase tracking-wide text-text-dim">
            {item.label}
          </div>
          <div className="mt-0.5 truncate text-[12.5px] font-medium text-text-main" title={item.value}>
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function InstructionBlock({ markdown }: { markdown: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`mb-1 flex w-full items-center gap-2 text-left ${FOCUS_RING}`}
      >
        <Sym name={open ? "expand_more" : "chevron_right"} size={18} className="text-text-dim" />
        <span className="h-4 w-0.5 shrink-0 rounded-full bg-primary" aria-hidden />
        <Sym name="description" size={16} className="text-primary" />
        <h3 className="font-display text-[14.5px] font-semibold text-text-main">{t("experiments.detail.instruction")}</h3>
      </button>
      {open ? (
        <div className="max-h-[420px] overflow-auto rounded-lg border border-outline/30 bg-surface/40 p-3">
          <Markdown className="text-[12.5px]">{markdown}</Markdown>
        </div>
      ) : null}
    </div>
  );
}

function RunCohortMixPanel({ mix }: { mix: ExperimentCohortMix | null | undefined }) {
  const { t } = useI18n();
  if (!mix) return null;
  if (mix.note && mix.dimensions.length === 0) {
    return <p className="mt-3 text-[12px] text-text-dim">{mix.note}</p>;
  }
  if (mix.dimensions.length === 0) return null;
  return (
    <div className="mt-3 space-y-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[11px] font-medium uppercase tracking-wide text-text-dim">
          {t("experiments.detail.cohortMix")}
        </div>
        <div className="text-[11.5px] text-text-dim">
          {mix.resolved}/{mix.n}
          {mix.missing > 0 ? ` · ${t("experiments.detail.missingAttrs", { count: mix.missing })}` : ""}
        </div>
      </div>
      {mix.dimensions.map((dim) => (
        <div
          key={dim.id}
          className="rounded-md border border-outline/20 bg-surface/30 px-2.5 py-2"
        >
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <span className="text-[12.5px] font-semibold text-text-main">
              {humanizeToken(dim.id)}
            </span>
            {dim.stratify ? (
              <span className="text-[10.5px] font-medium uppercase tracking-wide text-secondary">
                {t("experiments.detail.stratify")}
              </span>
            ) : null}
            <MetaChip tone={dim.match === "match" ? "secondary" : "warn"}>
              {dim.match === "match" ? t("experiments.detail.matchOk") : t("experiments.detail.matchMismatch")}
            </MetaChip>
          </div>
          <div className="flex flex-wrap gap-1">
            {dim.buckets.map((b) => {
              const pct = `${Math.round(b.pct * 100)}%`;
              const expected =
                typeof b.expectedPct === "number"
                  ? `${Math.round(b.expectedPct * 100)}%`
                  : null;
              const bad = !b.inContract || b.shareOk === false;
              return (
                <span
                  key={b.value}
                  title={
                    expected != null
                      ? t("experiments.detail.bucketTipExpected", {
                          count: b.count,
                          pct,
                          expected,
                        })
                      : t("experiments.detail.bucketTip", { count: b.count, pct })
                  }
                  className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11.5px] ${
                    bad
                      ? "bg-warn/15 text-warn"
                      : "bg-surface-high/70 text-text-variant"
                  }`}
                >
                  <span className={bad ? "font-medium" : "text-text-main"}>{b.value}</span>
                  <span className="tabular-nums text-text-dim">
                    {b.count}
                    <span className="mx-0.5 opacity-50">·</span>
                    {pct}
                    {expected != null ? (
                      <span className="opacity-70"> / {expected}</span>
                    ) : null}
                  </span>
                  {!b.inContract ? (
                    <span className="text-[10px] font-medium uppercase tracking-wide">{t("experiments.detail.extra")}</span>
                  ) : null}
                </span>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function RunVsContractChip({
  strategy,
  runN,
  mix,
}: {
  strategy: ExperimentCohortStrategy | null | undefined;
  runN: number | null;
  mix?: ExperimentCohortMix | null;
}) {
  const { t } = useI18n();
  const expected = contractExpectedN(strategy);
  const sizeOk = expected.n != null && runN != null && runN === expected.n;
  const sizeKnown = expected.n != null && runN != null;
  const mixStatus = mix?.vsContract;

  if (!sizeKnown && (!mixStatus || mixStatus === "unknown")) {
    return <MetaChip tone="neutral">{t("experiments.detail.runVsContractNa")}</MetaChip>;
  }
  if (sizeOk && (mixStatus === "match" || !mixStatus || mixStatus === "unknown")) {
    return <MetaChip tone="secondary">{t("experiments.detail.matchesContract")}</MetaChip>;
  }
  const bits: string[] = [];
  if (sizeKnown && !sizeOk) bits.push(`n ${runN} ≠ ${expected.n}`);
  if (mixStatus === "mismatch" || mixStatus === "partial") bits.push("mix ≠");
  return (
    <MetaChip tone="warn">
      {bits.length > 0 ? bits.join(" · ") : t("experiments.detail.differsFromContract")}
    </MetaChip>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return m ? `${h}h ${m}m` : `${h}h`;
}

function samplingLabel(manifest: ExperimentManifest): string {
  if (manifest.axis === "put") {
    const dim = manifest.sampling.dimension ?? manifest.design.putDimension ?? "persona";
    const total = (manifest.sampling.arms ?? []).reduce(
      (sum, a) => sum + (a.personaCount ?? 0),
      0,
    );
    return `${dim} · ${total} personas · seed ${manifest.sampling.seed}`;
  }
  const perArm = manifest.sampling.perArm;
  return `perArm ${perArm ?? "—"} · seed ${manifest.sampling.seed}`;
}

/** One package for the whole experiment (Setup + Results; Analysis when present). */
