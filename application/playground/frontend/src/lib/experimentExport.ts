import type {
  ExperimentAnalysis,
  ExperimentComparison,
  ExperimentManifest,
} from "@/lib/types";

/**
 * Client-side export builders for an experiment run. Kept framework-free so the
 * same JSON/CSV shape can be reused across surfaces (and mirrors the columns the
 * `matraix experiment analyze --format csv` CLI emits).
 */

export function buildExperimentJson(
  manifest: ExperimentManifest,
  analysis: ExperimentAnalysis | null,
): string {
  const payload = {
    kind: "matraix.experiment.report",
    version: 1,
    exportedAt: new Date().toISOString(),
    setup: {
      experimentId: manifest.experimentId,
      name: manifest.name,
      task: manifest.task,
      hypothesis: manifest.hypothesis ?? null,
      status: manifest.status,
      axis: manifest.axis,
      design: manifest.design,
      sampling: manifest.sampling,
      cohortStrategy: manifest.cohortStrategy ?? null,
      cohortMix: manifest.cohortMix ?? null,
      instructionMarkdown: manifest.instructionMarkdown ?? null,
      personaModel: manifest.personaModel ?? null,
      metricContract: manifest.metricContract,
      cells: manifest.cells,
      progress: manifest.progress,
      costUsd: manifest.costUsd ?? null,
      durationSeconds: manifest.durationSeconds ?? null,
    },
    results: analysis
      ? {
          baselineCell: analysis.baselineCell,
          baselineArm: analysis.baselineArm ?? null,
          correction: analysis.correction,
          armSizes: analysis.armSizes,
          comparisons: analysis.comparisons,
        }
      : null,
    analysis: analysis
      ? {
          sliceableDimensions: analysis.sliceableDimensions ?? [],
          slices: analysis.slices ?? null,
          sliceDrivers: analysis.sliceDrivers ?? [],
        }
      : null,
    analysisNote: analysis
      ? "Includes scorecard comparisons and persona-attribute slices when available."
      : "No analysis payload yet — re-export after trials produce metrics.",
  };
  return JSON.stringify(payload, null, 2);
}

const CSV_COLUMNS = [
  "experiment_id",
  "experiment_name",
  "task",
  "axis",
  "metric_key",
  "role",
  "kind",
  "arm",
  "cell_id",
  "baseline_arm",
  "baseline_cell",
  "test",
  "paired",
  "n_baseline",
  "n_treatment",
  "baseline_mean",
  "treatment_mean",
  "diff",
  "delta_pct",
  "effect_type",
  "effect_size",
  "ci_low",
  "ci_high",
  "p_value",
  "p_value_adj",
  "significant",
  "reason",
  "categories",
  "treatment_distribution",
] as const;

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = typeof value === "string" ? value : String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function comparisonRow(
  manifest: ExperimentManifest,
  analysis: ExperimentAnalysis,
  cmp: ExperimentComparison,
): Record<(typeof CSV_COLUMNS)[number], unknown> {
  const effect = cmp.effect ?? {};
  const effectType =
    typeof effect.cohensD === "number"
      ? "cohens_d"
      : typeof effect.cramersV === "number"
        ? "cramers_v"
        : typeof effect.deltaPct === "number"
          ? "delta_pct"
          : "";
  const effectSize =
    typeof effect.cohensD === "number"
      ? effect.cohensD
      : typeof effect.cramersV === "number"
        ? effect.cramersV
        : typeof effect.deltaPct === "number"
          ? effect.deltaPct
          : "";
  const ci = effect.ciPct ?? effect.ci;
  return {
    experiment_id: manifest.experimentId,
    experiment_name: manifest.name ?? "",
    task: manifest.task,
    axis: manifest.axis ?? "",
    metric_key: cmp.metricKey,
    role: cmp.role,
    kind: cmp.kind,
    arm: cmp.arm ?? cmp.cellId,
    cell_id: cmp.cellId,
    baseline_arm: analysis.baselineArm ?? "",
    baseline_cell: analysis.baselineCell ?? "",
    test: cmp.test ?? "",
    paired: cmp.paired ?? "",
    n_baseline: cmp.baseline?.n ?? "",
    n_treatment: cmp.treatment?.n ?? "",
    baseline_mean: cmp.baseline?.mean ?? "",
    treatment_mean: cmp.treatment?.mean ?? "",
    diff: effect.diff ?? "",
    delta_pct: effect.deltaPct ?? "",
    effect_type: effectType,
    effect_size: effectSize,
    ci_low: ci ? ci[0] : "",
    ci_high: ci ? ci[1] : "",
    p_value: cmp.pValue ?? "",
    p_value_adj: cmp.pValueAdj ?? "",
    significant: cmp.significant ? "true" : "false",
    reason: cmp.reason ?? "",
    categories: cmp.categories && cmp.categories.length > 0 ? cmp.categories.join("|") : "",
    treatment_distribution: cmp.treatment?.distribution
      ? JSON.stringify(cmp.treatment.distribution)
      : "",
  };
}

export function buildExperimentCsv(
  manifest: ExperimentManifest,
  analysis: ExperimentAnalysis | null,
): string {
  const header = CSV_COLUMNS.join(",");
  if (!analysis || analysis.comparisons.length === 0) {
    return `${header}\n`;
  }
  const lines = analysis.comparisons.map((cmp) => {
    const row = comparisonRow(manifest, analysis, cmp);
    return CSV_COLUMNS.map((col) => csvCell(row[col])).join(",");
  });
  return `${header}\n${lines.join("\n")}\n`;
}

export function downloadTextFile(
  filename: string,
  contents: string,
  mime: string,
): void {
  const blob = new Blob([contents], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadExperimentJson(
  manifest: ExperimentManifest,
  analysis: ExperimentAnalysis | null,
): void {
  downloadTextFile(
    `${manifest.experimentId}-report.json`,
    buildExperimentJson(manifest, analysis),
    "application/json",
  );
}

export function downloadExperimentCsv(
  manifest: ExperimentManifest,
  analysis: ExperimentAnalysis | null,
): void {
  downloadTextFile(
    `${manifest.experimentId}-scorecard.csv`,
    buildExperimentCsv(manifest, analysis),
    "text/csv",
  );
}
