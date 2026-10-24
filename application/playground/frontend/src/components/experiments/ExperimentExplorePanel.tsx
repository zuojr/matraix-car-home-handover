import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  ExperimentAnalysis,
  ExperimentArmSummary,
  ExperimentComparison,
  ExperimentManifest,
  ExperimentPersonaSlices,
  ExperimentSliceDriver,
  ExperimentSliceRow,
} from "@/lib/types";
import { useI18n } from "@/i18n/I18nProvider";
import type { MessageKey } from "@/i18n/types";
import { translateMetricDescription } from "@/lib/metricInfo";
import { humanizeToken } from "../cockpit/cockpitShared";
import { CockpitSelect } from "../cockpit/setup/CockpitSelect";
import { StudioGlassPanel } from "../studio/StudioShell";
import { MetaChip, SectionHeader } from "./experimentShared";

/**
 * Exploratory analysis (Statsig / Eppo / Amplitude-style “dig deeper”):
 * Effect table is the metric directory; click a row for absolute levels.
 * Persona attribute slices show heterogeneous effects — not individual personas.
 */
export interface ExperimentExplorePanelProps {
  experimentId: string;
  manifest: ExperimentManifest;
  confidence: number;
  fdr: boolean;
  pending: boolean;
}

type NumericScale = "binary" | "score" | "count" | "continuous";

export function ExperimentExplorePanel({
  experimentId,
  manifest,
  confidence,
  fdr,
  pending,
}: ExperimentExplorePanelProps) {
  const { t } = useI18n();
  // Local-only until the operator picks — avoids a second full fetch on mount.
  const [focusMetric, setFocusMetric] = useState<string | null>(null);
  const [driverMetric, setDriverMetric] = useState<string | null>(null);
  const [driverArm, setDriverArm] = useState<string | null>(null);
  const [sliceDim, setSliceDim] = useState<string | null>(null);

  // Progressive load: scorecard first (shared cache with Results tab), then the
  // expensive persona-slice / driver ranking in the background. 300-trial runs
  // otherwise block the whole Analysis tab on YAML I/O + multi-dim scans.
  const baseQuery = useQuery<ExperimentAnalysis>({
    queryKey: ["experiment-analysis", experimentId, confidence, fdr],
    queryFn: () => api.getExperimentAnalysis(experimentId, confidence, fdr),
    enabled: !pending,
    staleTime: 60_000,
  });

  const slicesQuery = useQuery<ExperimentAnalysis>({
    queryKey: [
      "experiment-analysis-explore",
      experimentId,
      confidence,
      fdr,
      sliceDim,
      driverMetric,
    ],
    queryFn: () =>
      api.getExperimentAnalysis(experimentId, confidence, fdr, {
        includeSlices: true,
        sliceDimension: sliceDim ?? undefined,
        // Drivers + segment table follow this metric (default: primary on server).
        sliceMetric: driverMetric ?? undefined,
      }),
    enabled: !pending,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  // Prefer slices payload when ready (same comparisons + drivers); fall back to
  // the fast scorecard so Effect explorer paints immediately.
  const analysis = slicesQuery.data ?? baseQuery.data;
  const comparisons = analysis?.comparisons ?? [];
  const slicesReady = Boolean(slicesQuery.data);
  const slicesLoading = slicesQuery.isFetching || (slicesQuery.isPending && !slicesQuery.data);
  const controlLabel =
    analysis?.baselineArm ||
    manifest.cells.find((c) => c.baseline)?.arm ||
    manifest.cells.find((c) => c.baseline)?.cellId ||
    "control";
  const metricKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const c of comparisons) keys.add(c.metricKey);
    return [...keys];
  }, [comparisons]);

  const numericalMetrics = useMemo(() => {
    const keys: string[] = [];
    const seen = new Set<string>();
    for (const c of comparisons) {
      if (c.kind !== "numerical" || seen.has(c.metricKey)) continue;
      seen.add(c.metricKey);
      keys.push(c.metricKey);
    }
    return keys;
  }, [comparisons]);

  const primary = analysis?.metricContract?.primary?.[0] ?? null;
  const activeMetric =
    (focusMetric && metricKeys.includes(focusMetric) ? focusMetric : null) ??
    (primary && metricKeys.includes(primary) ? primary : null) ??
    metricKeys[0] ??
    null;
  const activeDriverMetric =
    (driverMetric && numericalMetrics.includes(driverMetric) ? driverMetric : null) ??
    (primary && numericalMetrics.includes(primary) ? primary : null) ??
    numericalMetrics[0] ??
    null;

  const focused = useMemo(
    () => comparisons.filter((c) => c.metricKey === activeMetric),
    [comparisons, activeMetric],
  );
  const focusKind = focused[0]?.kind ?? null;
  const focusScale = resolveScale(focused[0]);

  const driverArms = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of analysis?.sliceDrivers ?? []) {
      const id = d.cellId || d.arm || "";
      if (!id) continue;
      map.set(id, d.arm || id);
    }
    return [...map.entries()].map(([id, label]) => ({ id, label }));
  }, [analysis?.sliceDrivers]);

  const activeDriverArm =
    (driverArm && driverArms.some((a) => a.id === driverArm) ? driverArm : null) ??
    driverArms[0]?.id ??
    null;

  const activeSliceDim =
    sliceDim ??
    analysis?.slices?.dimension ??
    analysis?.sliceableDimensions?.[0]?.id ??
    null;

  const onFocusMetric = (key: string) => {
    setFocusMetric(key);
    // Numerical metrics can also become the driver target in one click.
    if (numericalMetrics.includes(key)) {
      setDriverMetric(key);
      setSliceDim(null); // let server pick top driver for the new metric
    }
  };

  if (pending) {
    return (
      <StudioGlassPanel className="p-4">
        <SectionHeader icon="query_stats" title={t("experiments.explore.analysis")} />
        <p className="mt-2 text-[12.5px] text-text-dim">
          {t("experiments.explore.waiting")}
        </p>
      </StudioGlassPanel>
    );
  }

  // Only block the tab on the fast scorecard fetch — not on slice ranking.
  if (baseQuery.isPending && !analysis) {
    return (
      <StudioGlassPanel className="p-4">
        <SectionHeader icon="query_stats" title={t("experiments.explore.analysis")} />
        <p className="mt-2 text-[12.5px] text-text-dim">
          {t("experiments.explore.loading")}
        </p>
      </StudioGlassPanel>
    );
  }

  if (!analysis || comparisons.length === 0) {
    return (
      <StudioGlassPanel className="p-4">
        <SectionHeader icon="query_stats" title={t("experiments.explore.analysis")} />
        <p className="mt-2 text-[12.5px] text-text-dim">
          {t("experiments.explore.noComparisons")}
        </p>
      </StudioGlassPanel>
    );
  }

  return (
    <div className="space-y-4">
      <StudioGlassPanel className="p-4">
        <SectionHeader
          icon="table"
          title={t("experiments.explore.effects")}
          hint={t("experiments.explore.selectMetric")}
        />
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-outline/40 text-left text-[11px] uppercase tracking-wide text-text-dim">
                <th className="py-2 pr-3 font-medium">{t("experiments.explore.col.metric")}</th>
                <th className="py-2 pr-3 font-medium">{t("experiments.explore.col.type")}</th>
                <th className="py-2 pr-3 font-medium">{t("experiments.explore.col.arm")}</th>
                <th className="py-2 pr-3 font-medium">{t("experiments.explore.col.absolute")}</th>
                <th className="py-2 pr-3 font-medium">{t("experiments.explore.col.relative")}</th>
                <th className="py-2 pr-3 font-medium">p</th>
                <th className="py-2 font-medium">{t("experiments.explore.col.sig")}</th>
              </tr>
            </thead>
            <tbody>
              {comparisons.map((cmp) => {
                const selected = cmp.metricKey === activeMetric;
                return (
                  <tr
                    key={`${cmp.cellId}-${cmp.metricKey}`}
                    role="button"
                    tabIndex={0}
                    aria-selected={selected}
                    onClick={() => onFocusMetric(cmp.metricKey)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onFocusMetric(cmp.metricKey);
                      }
                    }}
                    className={`cursor-pointer border-b border-outline/15 transition ${
                      selected
                        ? "bg-primary/[0.08]"
                        : "hover:bg-surface-high/50"
                    }`}
                  >
                    <td className="py-2 pr-3 font-medium text-text-main">
                      {(() => {
                        const desc = translateMetricDescription(t, cmp.metricKey);
                        return (
                          <>
                            <span title={desc ?? cmp.metricKey}>
                              {humanizeToken(cmp.metricKey)}
                            </span>
                            {desc ? (
                              <span className="mt-0.5 block max-w-[260px] text-[10.5px] font-normal leading-snug text-text-dim">
                                {desc}
                              </span>
                            ) : null}
                          </>
                        );
                      })()}
                    </td>
                    <td className="py-2 pr-3 text-text-dim">{t(SCALE_BADGE_KEYS[scaleBadgeBucket(cmp)])}</td>
                    <td className="py-2 pr-3 text-text-variant">{cmp.arm || cmp.cellId}</td>
                    <td className="py-2 pr-3 tabular-nums text-text-main">
                      {absoluteEffectText(cmp)}
                    </td>
                    <td className="py-2 pr-3 tabular-nums text-text-variant">
                      {relativeEffectText(cmp)}
                    </td>
                    <td className="py-2 pr-3 tabular-nums text-text-dim">
                      {typeof cmp.pValue === "number"
                        ? cmp.pValue < 0.001
                          ? "<0.001"
                          : cmp.pValue.toFixed(3)
                        : "—"}
                    </td>
                    <td className="py-2">
                      {cmp.significant ? (
                        <MetaChip tone="secondary">{t("experiments.explore.yes")}</MetaChip>
                      ) : (
                        <span className="text-text-dim">{t("experiments.explore.no")}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </StudioGlassPanel>

      {activeMetric && focused.length > 0 ? (
        <StudioGlassPanel className="p-4">
          <SectionHeader
            icon="stacked_line_chart"
            title={humanizeToken(activeMetric)}
            right={<MetaChip tone="neutral">{t(SCALE_LABEL_KEYS[scaleLabelBucket(focusKind, focusScale)])}</MetaChip>}
          />
          <div className="mt-3 space-y-3">
            {focused.map((cmp) => (
              <MetricArmCard
                key={`${cmp.cellId}-${cmp.metricKey}`}
                cmp={cmp}
                controlLabel={controlLabel}
              />
            ))}
          </div>
        </StudioGlassPanel>
      ) : null}

      <PersonaSlicesBlock
        manifest={manifest}
        sliceable={slicesReady ? (analysis.sliceableDimensions ?? []) : []}
        slices={slicesReady ? analysis.slices : null}
        drivers={slicesReady ? (analysis.sliceDrivers ?? []) : []}
        sliceDim={activeSliceDim}
        onSliceDimChange={setSliceDim}
        activeMetric={activeMetric}
        driverMetric={activeDriverMetric}
        numericalMetrics={numericalMetrics}
        onDriverMetricChange={(key) => {
          setDriverMetric(key);
          setSliceDim(null);
        }}
        driverArms={driverArms}
        driverArm={activeDriverArm}
        onDriverArmChange={(id) => {
          setDriverArm(id);
          setSliceDim(null);
        }}
        loading={slicesLoading}
      />
    </div>
  );
}

function PersonaSlicesBlock({
  manifest,
  sliceable,
  slices,
  drivers,
  sliceDim,
  onSliceDimChange,
  activeMetric,
  driverMetric,
  numericalMetrics,
  onDriverMetricChange,
  driverArms,
  driverArm,
  onDriverArmChange,
  loading,
}: {
  manifest: ExperimentManifest;
  sliceable: NonNullable<ExperimentAnalysis["sliceableDimensions"]>;
  slices: ExperimentPersonaSlices | null | undefined;
  drivers: ExperimentSliceDriver[];
  sliceDim: string | null;
  onSliceDimChange: (id: string) => void;
  activeMetric: string | null;
  driverMetric: string | null;
  numericalMetrics: string[];
  onDriverMetricChange: (key: string) => void;
  driverArms: Array<{ id: string; label: string }>;
  driverArm: string | null;
  onDriverArmChange: (id: string) => void;
  loading: boolean;
}) {
  const { t } = useI18n();
  const metricLabel = humanizeToken(
    slices?.metricKey || driverMetric || activeMetric || "primary",
  );
  const armDrivers = useMemo(() => {
    if (!driverArm) return drivers;
    return drivers.filter((d) => (d.cellId || d.arm) === driverArm);
  }, [drivers, driverArm]);
  const multiArm = driverArms.length > 1;

  return (
    <StudioGlassPanel className="p-4">
      <SectionHeader
        icon="group"
        title={t("experiments.explore.drivers")}
        hint={metricLabel}
        right={
          loading ? (
            <span className="text-[11px] text-text-dim">
              {t("experiments.explore.updating")}
            </span>
          ) : null
        }
      />

      {loading && sliceable.length === 0 ? (
        <p className="mt-3 text-[12.5px] text-text-dim">
          {t("experiments.explore.loadingSlices")}
        </p>
      ) : sliceable.length === 0 ? (
        <p className="mt-3 text-[12.5px] text-text-dim">
          {t("experiments.explore.noSliceable")}
        </p>
      ) : (
        <>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
            {numericalMetrics.length > 0 ? (
              <div className="min-w-[220px] flex-1">
                <CockpitSelect
                  label={t("experiments.explore.col.metric")}
                  inlineLabel
                  value={driverMetric ?? numericalMetrics[0] ?? ""}
                  options={numericalMetrics.map((key) => ({
                    value: key,
                    label: humanizeToken(key),
                    meta:
                      key === (manifest.metricContract?.primary?.[0] ?? "")
                        ? t("experiments.explore.primary")
                        : undefined,
                  }))}
                  onChange={onDriverMetricChange}
                  showSelectedMeta
                />
              </div>
            ) : (
              <p className="text-[12.5px] text-text-dim">
                {t("experiments.explore.driversNeedNumerical")}
              </p>
            )}
            {multiArm ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11.5px] font-medium uppercase tracking-wide text-text-dim">
                  {t("experiments.explore.col.arm")}
                </span>
                {driverArms.map((arm) => (
                  <button
                    key={arm.id}
                    type="button"
                    onClick={() => onDriverArmChange(arm.id)}
                    className={`rounded-md px-2.5 py-1 text-[12px] font-medium transition ${
                      driverArm === arm.id
                        ? "bg-primary text-on-primary"
                        : "bg-surface-high/70 text-text-variant hover:text-text-main"
                    }`}
                  >
                    {arm.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          {armDrivers.length > 0 ? (
            <div className="mt-3 space-y-2">
              {armDrivers.map((driver, idx) => {
                const selected = driver.dimension === sliceDim;
                return (
                  <button
                    key={`${driver.cellId}-${driver.dimension}`}
                    type="button"
                    onClick={() => onSliceDimChange(driver.dimension)}
                    className={`w-full rounded-lg border px-3 py-2.5 text-left transition ${
                      selected
                        ? "border-primary/40 bg-primary/[0.08]"
                        : "border-outline/25 bg-surface/40 hover:border-outline/50 hover:bg-surface-high/40"
                    }`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[10.5px] font-semibold uppercase tracking-wide text-text-dim">
                            #{idx + 1}
                          </span>
                          <span className="text-[13px] font-semibold text-text-main">
                            {humanizeToken(driver.dimension)}
                          </span>
                          <MetaChip tone="neutral">
                            {t("experiments.explore.spread", {
                              value: formatDriverDiff(driver.spread, driver.scale),
                            })}
                          </MetaChip>
                        </div>
                        <p className="mt-1 text-[12.5px] text-text-variant">
                          <span className="font-medium text-secondary">{driver.highest.value}</span>
                          {" "}
                          {formatDriverDiff(driver.highest.diff, driver.scale)}
                          {driver.highest.significant ? ` · ${t("experiments.explore.sig")}` : ""}
                          {" · "}
                          <span className="font-medium text-danger">{driver.lowest.value}</span>
                          {" "}
                          {formatDriverDiff(driver.lowest.diff, driver.scale)}
                          {driver.lowest.significant ? ` · ${t("experiments.explore.sig")}` : ""}
                        </p>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="mt-3 text-[12.5px] text-text-dim">
              {t("experiments.explore.noDrivers")}
            </p>
          )}

          <div className="mt-4 max-w-md">
            <CockpitSelect
              label={t("experiments.explore.attribute")}
              inlineLabel
              value={sliceDim ?? sliceable[0]?.id ?? ""}
              options={sliceable.map((d) => ({
                value: d.id,
                label: humanizeToken(d.id),
                meta: t("experiments.explore.valuesCount", { count: d.distinctValues }),
              }))}
              onChange={onSliceDimChange}
              showSelectedMeta={false}
            />
          </div>

          {slices && slices.rows.length > 0 ? (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="border-b border-outline/40 text-left text-[11px] uppercase tracking-wide text-text-dim">
                    <th className="py-2 pr-3 font-medium">
                      {humanizeToken(slices.dimension)}
                    </th>
                    <th className="py-2 pr-3 font-medium">{t("experiments.explore.col.arm")}</th>
                    <th className="py-2 pr-3 font-medium">n</th>
                    <th className="py-2 pr-3 font-medium">{t("experiments.explore.col.absolute")}</th>
                    <th className="py-2 pr-3 font-medium">{t("experiments.explore.col.relative")}</th>
                    <th className="py-2 pr-3 font-medium">p</th>
                    <th className="py-2 pr-3 font-medium">{t("experiments.explore.col.sig")}</th>
                    <th className="py-2 font-medium">{t("experiments.explore.col.guardrails")}</th>
                  </tr>
                </thead>
                <tbody>
                  {slices.rows
                    .filter((row) =>
                      !driverArm ? true : (row.cellId || row.arm) === driverArm,
                    )
                    .map((row) => (
                      <SliceRow key={`${row.cellId}-${row.value}`} row={row} />
                    ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-3 text-[12.5px] text-text-dim">
              {t("experiments.explore.notEnoughN")}
            </p>
          )}

          {slices && slices.skipped.length > 0 ? (
            <p className="mt-2 text-[11.5px] text-text-dim">
              {t("experiments.explore.skipped", { count: slices.skipped.length })}
            </p>
          ) : null}
        </>
      )}
    </StudioGlassPanel>
  );
}

function SliceRow({ row }: { row: ExperimentSliceRow }) {
  const { t } = useI18n();
  const asCmp = row as unknown as ExperimentComparison;
  return (
    <tr className="border-b border-outline/15">
      <td className="py-2 pr-3 font-medium text-text-main">{row.value}</td>
      <td className="py-2 pr-3 text-text-variant">{row.arm || row.cellId}</td>
      <td className="py-2 pr-3 tabular-nums text-text-dim">
        {row.nBaseline}/{row.nTreatment}
      </td>
      <td className="py-2 pr-3 tabular-nums text-text-main">
        {absoluteEffectText(asCmp)}
      </td>
      <td className="py-2 pr-3 tabular-nums text-text-variant">
        {relativeEffectText(asCmp)}
      </td>
      <td className="py-2 pr-3 tabular-nums text-text-dim">
        {typeof row.pValue === "number"
          ? row.pValue < 0.001
            ? "<0.001"
            : row.pValue.toFixed(3)
          : "—"}
      </td>
      <td className="py-2 pr-3">
        {row.significant ? (
          <MetaChip tone="secondary">{t("experiments.explore.yes")}</MetaChip>
        ) : (
          <span className="text-text-dim">{t("experiments.explore.no")}</span>
        )}
      </td>
      <td className="py-2 text-[11.5px] text-text-variant">
        {(row.guardrails ?? []).length === 0
          ? "—"
          : (row.guardrails ?? []).map((g) => {
              const d = g.diff;
              const tone =
                typeof d === "number" && d < 0
                  ? "text-danger"
                  : typeof d === "number" && d > 0
                    ? "text-secondary"
                    : "text-text-dim";
              return (
                <span key={g.metricKey} className={`mr-2 inline-block tabular-nums ${tone}`}>
                  {humanizeToken(g.metricKey)}{" "}
                  {typeof d === "number" ? `${d >= 0 ? "+" : ""}${d.toFixed(2)}` : "—"}
                  {g.significant ? "*" : ""}
                </span>
              );
            })}
      </td>
    </tr>
  );
}

function MetricArmCard({
  cmp,
  controlLabel,
}: {
  cmp: ExperimentComparison;
  controlLabel: string;
}) {
  const { t } = useI18n();
  if (cmp.kind === "categorical") {
    return <CategoricalArmCard cmp={cmp} controlLabel={controlLabel} />;
  }
  if (cmp.kind !== "numerical") return null;

  const scale = resolveScale(cmp);
  const base = cmp.baseline;
  const treat = cmp.treatment;
  const diff = cmp.effect?.diff;
  const deltaPct = cmp.effect?.deltaPct;
  const ci = cmp.effect?.ci;
  const treatLabel = cmp.arm || cmp.cellId || "treatment";
  const sigClass = cmp.significant
    ? (diff ?? 0) >= 0
      ? "text-secondary"
      : "text-danger"
    : "text-text-variant";

  return (
    <div className="rounded-lg border border-outline/25 bg-surface/30 px-3 py-3">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[13px] font-semibold text-text-main">{treatLabel}</div>
          <div className="mt-0.5 text-[11.5px] text-text-dim">
            {cmp.paired
              ? t("experiments.explore.comparedToPaired", { control: controlLabel })
              : t("experiments.explore.comparedTo", { control: controlLabel })}
            {typeof cmp.pValue === "number"
              ? ` · p=${cmp.pValue < 0.001 ? "<0.001" : cmp.pValue.toFixed(3)}`
              : ""}
          </div>
        </div>
        <div className={`text-right ${sigClass}`}>
          <div className="text-[15px] font-semibold tabular-nums leading-tight">
            {absoluteEffectText(cmp)}
          </div>
          <div className="text-[11.5px] tabular-nums text-text-dim">
            {relativeEffectText(cmp)}
            {ci && typeof diff === "number"
              ? ` · CI [${formatAbs(ci[0], scale)}, ${formatAbs(ci[1], scale)}]`
              : typeof deltaPct === "number"
                ? ""
                : ""}
          </div>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <LevelCard
          label={controlLabel}
          roleHint={t("experiments.explore.roleHint.control")}
          scale={scale}
          summary={base}
          tone="muted"
        />
        <LevelCard
          label={treatLabel}
          roleHint={t("experiments.explore.roleHint.treatment")}
          scale={scale}
          summary={treat}
          tone="accent"
        />
      </div>

      {scale === "count" && base && treat ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <TotalChip
            label={t("experiments.explore.totalChip", { label: controlLabel })}
            value={base.sum}
          />
          <TotalChip
            label={t("experiments.explore.totalChip", { label: treatLabel })}
            value={treat.sum}
          />
        </div>
      ) : null}

      {scale === "score" && base && treat ? (
        <p className="mt-2 text-[11.5px] text-text-dim">
          {t("experiments.explore.range", {
            baseMin: fmtNum(base.min),
            baseMax: fmtNum(base.max),
            treatMin: fmtNum(treat.min),
            treatMax: fmtNum(treat.max),
          })}
          {typeof base.median === "number" && typeof treat.median === "number"
            ? t("experiments.explore.median", {
                baseMedian: fmtNum(base.median),
                treatMedian: fmtNum(treat.median),
              })
            : ""}
        </p>
      ) : null}
    </div>
  );
}

function LevelCard({
  label,
  roleHint,
  scale,
  summary,
  tone,
}: {
  label: string;
  roleHint?: string;
  scale: NumericScale;
  summary: ExperimentArmSummary | undefined;
  tone: "muted" | "accent";
}) {
  const { t } = useI18n();
  // Accent = treatment identity (sky), not significance.
  const shell =
    tone === "accent"
      ? "border-sky-400/35 bg-sky-400/[0.08]"
      : "border-amber-300/35 bg-amber-300/[0.08]";
  const primary = primaryLevel(summary, scale);
  const secondary = secondaryLevel(t, summary, scale);
  return (
    <div className={`rounded-md border px-2.5 py-2 ${shell}`}>
      <div className="text-[10.5px] font-medium uppercase tracking-wide text-text-dim">
        {label}
        {roleHint ? ` · ${roleHint}` : ""} · {t(LEVEL_NOUN_KEYS[levelNounBucket(scale)])}
      </div>
      <div className="mt-1 font-mono text-[18px] font-semibold tabular-nums leading-none text-text-main">
        {primary}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-text-dim">
        {typeof summary?.n === "number" ? <span>n={summary.n}</span> : null}
        {secondary ? <span>{secondary}</span> : null}
      </div>
    </div>
  );
}

function TotalChip({ label, value }: { label: string; value?: number | null }) {
  return (
    <div className="rounded-md bg-surface-high/50 px-2.5 py-1.5 text-[12px]">
      <span className="text-text-dim">{label}</span>
      <span className="ml-2 font-mono font-semibold tabular-nums text-text-main">
        {typeof value === "number" ? Math.round(value).toLocaleString() : "—"}
      </span>
    </div>
  );
}

function CategoricalArmCard({
  cmp,
  controlLabel,
}: {
  cmp: ExperimentComparison;
  controlLabel: string;
}) {
  const { t } = useI18n();
  const cats = cmp.categories ?? Object.keys(cmp.treatment?.distribution ?? {});
  const v = cmp.effect?.cramersV;
  const treatLabel = cmp.arm || cmp.cellId || "treatment";
  return (
    <div className="rounded-lg border border-outline/25 bg-surface/30 px-3 py-3">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[13px] font-semibold text-text-main">{treatLabel}</div>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-text-dim">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-3 rounded-sm bg-amber-300" />
              {controlLabel}
              <span className="text-text-dim/80">· {t("experiments.explore.roleHint.control")}</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-3 rounded-sm bg-sky-400" />
              {treatLabel}
            </span>
          </div>
        </div>
        {typeof v === "number" ? (
          <div className="text-right">
            <div className="tabular-nums text-[12px] font-medium text-text-main">
              Cramér&apos;s V = {v.toFixed(2)}
            </div>
            <div className="text-[11px] text-text-dim">{t(CRAMERS_STRENGTH_KEYS[cramersStrengthBucket(v)])}</div>
          </div>
        ) : null}
      </div>
      <div className="space-y-2.5">
        {cats.map((cat) => {
          const b = cmp.baseline?.distribution?.[cat] ?? 0;
          const t = cmp.treatment?.distribution?.[cat] ?? 0;
          const deltaPp = (t - b) * 100;
          return (
            <div key={cat} className="text-[12px]">
              <div className="mb-1 flex items-baseline justify-between gap-2 text-text-variant">
                <span className="font-medium text-text-main">{humanizeToken(cat)}</span>
                <span className="tabular-nums text-text-dim">
                  {(b * 100).toFixed(0)}% → {(t * 100).toFixed(0)}%
                  <span
                    className={`ml-1.5 ${
                      Math.abs(deltaPp) < 0.5
                        ? "text-text-dim"
                        : deltaPp > 0
                          ? "text-secondary"
                          : "text-danger"
                    }`}
                  >
                    ({deltaPp >= 0 ? "+" : ""}
                    {deltaPp.toFixed(0)} pp)
                  </span>
                </span>
              </div>
              <div className="space-y-1">
                <div className="flex h-1.5 overflow-hidden rounded-full bg-surface-high">
                  <div
                    className="h-full rounded-full bg-amber-300"
                    style={{ width: `${Math.min(100, Math.max(0, b * 100))}%` }}
                  />
                </div>
                <div className="flex h-1.5 overflow-hidden rounded-full bg-surface-high">
                  <div
                    className="h-full rounded-full bg-sky-400"
                    style={{ width: `${Math.min(100, Math.max(0, t * 100))}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {typeof v === "number" ? (
        <p className="mt-2.5 text-[11.5px] text-text-dim">
          {t("experiments.explore.barsLegend", {
            control: controlLabel,
            treatment: treatLabel,
          })}
        </p>
      ) : null}
    </div>
  );
}

const CRAMERS_STRENGTH_KEYS = {
  negligible: "experiments.explore.strength.negligible",
  weak: "experiments.explore.strength.weak",
  moderate: "experiments.explore.strength.moderate",
  strong: "experiments.explore.strength.strong",
} as const satisfies Record<string, MessageKey>;

function cramersStrengthBucket(v: number): keyof typeof CRAMERS_STRENGTH_KEYS {
  if (v < 0.1) return "negligible";
  if (v < 0.2) return "weak";
  if (v < 0.4) return "moderate";
  return "strong";
}

function formatDriverDiff(diff: number, scale?: string): string {
  const sign = diff >= 0 ? "+" : "";
  const s = (scale || "").toLowerCase();
  if (s === "binary") return `${sign}${(diff * 100).toFixed(1)} pp`;
  if (s === "score") return `${sign}${diff.toFixed(2)} pts`;
  if (s === "count") return `${sign}${diff.toFixed(2)}`;
  return `${sign}${diff.toFixed(2)}`;
}

function resolveScale(cmp: ExperimentComparison | undefined): NumericScale {
  const raw = (cmp?.scale || "").toLowerCase();
  if (raw === "binary" || raw === "score" || raw === "count" || raw === "continuous") {
    return raw;
  }
  return "continuous";
}

const SCALE_BADGE_KEYS = {
  num: "experiments.explore.badge.num",
  cat: "experiments.explore.badge.cat",
  text: "experiments.explore.badge.text",
  rate: "experiments.explore.badge.rate",
  score: "experiments.explore.badge.score",
  count: "experiments.explore.badge.count",
} as const satisfies Record<string, MessageKey>;

function scaleBadgeBucket(cmp: ExperimentComparison | undefined): keyof typeof SCALE_BADGE_KEYS {
  if (!cmp) return "num";
  if (cmp.kind === "categorical") return "cat";
  if (cmp.kind === "textual") return "text";
  switch (resolveScale(cmp)) {
    case "binary":
      return "rate";
    case "score":
      return "score";
    case "count":
      return "count";
    default:
      return "num";
  }
}

const SCALE_LABEL_KEYS = {
  categorical: "experiments.explore.scale.categorical",
  rate: "experiments.explore.scale.rate",
  score: "experiments.explore.scale.score",
  count: "experiments.explore.scale.count",
  continuous: "experiments.explore.scale.continuous",
} as const satisfies Record<string, MessageKey>;

function scaleLabelBucket(kind: string | null, scale: NumericScale): keyof typeof SCALE_LABEL_KEYS {
  if (kind === "categorical") return "categorical";
  switch (scale) {
    case "binary":
      return "rate";
    case "score":
      return "score";
    case "count":
      return "count";
    default:
      return "continuous";
  }
}

const LEVEL_NOUN_KEYS = {
  rate: "experiments.explore.levelNoun.rate",
  meanScore: "experiments.explore.levelNoun.meanScore",
  meanCount: "experiments.explore.levelNoun.meanCount",
  mean: "experiments.explore.levelNoun.mean",
} as const satisfies Record<string, MessageKey>;

function levelNounBucket(scale: NumericScale): keyof typeof LEVEL_NOUN_KEYS {
  switch (scale) {
    case "binary":
      return "rate";
    case "score":
      return "meanScore";
    case "count":
      return "meanCount";
    default:
      return "mean";
  }
}

function primaryLevel(summary: ExperimentArmSummary | undefined, scale: NumericScale): string {
  const mean = summary?.mean;
  if (typeof mean !== "number") return "—";
  if (scale === "binary") return `${(mean * 100).toFixed(1)}%`;
  if (scale === "count") return mean.toFixed(2);
  if (scale === "score") return mean.toFixed(2);
  return mean.toFixed(3);
}

function secondaryLevel(
  t: (key: MessageKey, values?: Record<string, string | number>) => string,
  summary: ExperimentArmSummary | undefined,
  scale: NumericScale,
): string | null {
  if (!summary) return null;
  if (scale === "binary" && typeof summary.mean === "number" && typeof summary.n === "number") {
    const successes = Math.round(summary.mean * summary.n);
    return t("experiments.explore.positives", { count: successes, n: summary.n });
  }
  if (scale === "count" && typeof summary.sum === "number") {
    return t("experiments.explore.totalValue", { value: Math.round(summary.sum) });
  }
  if (typeof summary.std === "number") {
    return t("experiments.explore.sd", { value: summary.std.toFixed(2) });
  }
  return null;
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

function formatAbs(value: number, scale: NumericScale): string {
  if (scale === "binary") return `${(value * 100).toFixed(1)} pp`;
  if (scale === "score") return `${value.toFixed(2)} pts`;
  if (scale === "count") return value.toFixed(2);
  return value.toFixed(3);
}



function fmtNum(value: number | null | undefined): string {
  if (typeof value !== "number") return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}
