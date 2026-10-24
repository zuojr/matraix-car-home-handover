import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  ExperimentAxis,
  ExperimentTaskDetail as TaskDetail,
} from "@/lib/types";
import { useI18n } from "@/i18n/I18nProvider";
import { FOCUS_RING, Sym, humanizeToken } from "../cockpit/cockpitShared";
import { Markdown } from "../Markdown";
import { StudioGlassPanel } from "../studio/StudioShell";
import {
  AXIS_META,
  MetaChip,
  MetricContractSummary,
  SectionHeader,
  designLabel,
  errMessage,
} from "./experimentShared";

export interface ExperimentTaskDetailProps {
  taskPath: string;
  onConfigure: (taskPath: string) => void;
}

/**
 * Read-only detail page for a pre-configured experiment task. The only action is
 * "Configure run". The design section is axis-aware (SUT vs PUT) and always uses
 * human labels; control (baseline) is called out explicitly.
 */
export function ExperimentTaskDetail({
  taskPath,
  onConfigure,
}: ExperimentTaskDetailProps) {
  const { t } = useI18n();
  const detailQuery = useQuery<TaskDetail>({
    queryKey: ["experiment-task", taskPath],
    queryFn: () => api.getExperimentTask(taskPath),
    retry: false,
  });

  if (detailQuery.isLoading) {
    return <p className="text-[13px] text-text-dim">{t("experiments.taskDetail.loadingTask")}</p>;
  }
  if (detailQuery.isError || !detailQuery.data) {
    return (
      <p className="rounded-md bg-danger/10 p-3 text-[13px] text-danger" role="alert">
        {errMessage(detailQuery.error)}
      </p>
    );
  }

  const detail = detailQuery.data;
  const axis: ExperimentAxis = detail.axis === "put" ? "put" : "sut";
  const meta = AXIS_META[axis];

  return (
    <div className="space-y-4">
      {/* Header + CTA */}
      <StudioGlassPanel className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-display text-[17px] font-bold text-text-main">{detail.name}</h2>
            <div className="mt-0.5 font-mono text-[11.5px] text-text-dim">{detail.task}</div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px] text-text-variant">
              <span
                className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-bold ${
                  axis === "put" ? "bg-secondary/14 text-secondary" : "bg-primary/14 text-primary"
                }`}
                title={meta.blurb}
              >
                <Sym name={meta.icon} size={13} />
                {meta.code}
              </span>
              <MetaChip>{detail.appType ?? "?"}</MetaChip>
              {detail.verifier ? <MetaChip mono>{detail.verifier}</MetaChip> : null}
            </div>
          </div>
          <button
            type="button"
            onClick={() => onConfigure(detail.task)}
            className={`glow inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 font-display text-[14px] font-bold text-on-primary transition hover:bg-primary-dim ${FOCUS_RING}`}
          >
            <Sym name="tune" fill={1} size={18} />
            {t("experiments.taskDetail.configureRun")}
          </button>
        </div>
      </StudioGlassPanel>

      {/* Hypothesis */}
      <StudioGlassPanel className="p-4">
        <SectionHeader icon="lightbulb" title={t("experiments.taskDetail.hypothesis")} />
        {detail.hypothesis ? (
          <p className="text-[13.5px] leading-relaxed text-text-main">{detail.hypothesis}</p>
        ) : (
          <p className="text-[13px] italic text-text-dim">{t("experiments.taskDetail.none")}</p>
        )}
      </StudioGlassPanel>

      {/* Design (axis-aware, merged factor + arms) */}
      {axis === "put" ? (
        <PutDesignSection detail={detail} />
      ) : (
        <SutDesignSection detail={detail} />
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <StudioGlassPanel className="p-4">
          <SectionHeader icon="target" title={t("experiments.taskDetail.metrics")} />
          <MetricContractSummary contract={detail.metricContract} />
          {detail.signals.length > 0 ? (
            <div className="mt-3 border-t border-outline/20 pt-3">
              <div className="mb-1.5 text-[11.5px] font-medium text-text-dim">
                {t("experiments.taskDetail.signals", { count: detail.signals.length })}
              </div>
              <div className="space-y-1">
                {detail.signals.map((s) => (
                  <div key={s.key} className="flex items-center gap-2 text-[12px]">
                    <span className="rounded bg-surface-high/60 px-1.5 py-0.5 font-mono text-[10.5px] text-text-variant">
                      {s.kind}
                    </span>
                    <span className="text-text-main">{s.label || s.key}</span>
                    <span className="font-mono text-[10.5px] text-text-dim">{s.key}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </StudioGlassPanel>

        <StudioGlassPanel className="p-4">
          <SectionHeader icon="groups" title={t("experiments.taskDetail.cohort")} />
          <CohortStrategyView strategy={detail.cohortStrategy} />
        </StudioGlassPanel>
      </div>

      {detail.instructionMarkdown ? (
        <StudioGlassPanel className="p-4">
          <InstructionBlock markdown={detail.instructionMarkdown} />
        </StudioGlassPanel>
      ) : null}
    </div>
  );
}

/** Builds fid -> label and fid -> (lid -> label) lookups from the declared factors. */
function useLabelMaps(detail: TaskDetail) {
  return useMemo(() => {
    const factorLabel: Record<string, string> = {};
    const levelLabel: Record<string, Record<string, string>> = {};
    for (const f of detail.factors) {
      factorLabel[f.id] = f.label || f.id;
      levelLabel[f.id] = {};
      for (const lv of f.levels) levelLabel[f.id][lv.id] = lv.label || lv.id;
    }
    return { factorLabel, levelLabel };
  }, [detail]);
}

function SutDesignSection({ detail }: { detail: TaskDetail }) {
  const { t } = useI18n();
  const { factorLabel, levelLabel } = useLabelMaps(detail);
  const cells = detail.design.cells;
  // With a single factor, each level IS one arm — showing a separate level palette
  // would just repeat the arms. Only show the palette when arms are combinations
  // of 2+ factors (full-factorial / fractional), where it actually adds info.
  const multiFactor = detail.factors.length > 1;
  return (
    <StudioGlassPanel className="p-4">
      <SectionHeader
        icon="grid_view"
        title={t("experiments.taskDetail.design")}
        hint={`${designLabel(detail.design.effectiveType, t)} · ${cells.length} ${t("experiments.taskDetail.armsWord", { count: cells.length })}`}
      />

      {/* Factor palette — only when arms are combinations of 2+ factors */}
      {multiFactor ? (
        <div className="mb-3 space-y-2">
          {detail.factors.map((f) => (
            <div key={f.id} className="rounded-lg border border-outline/30 bg-surface/40 p-2.5">
              <div className="mb-1 text-[13px] font-semibold text-text-main">
                {f.label} <span className="font-mono text-[11px] text-text-dim">{f.id}</span>
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
                    {lv.label}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {/* Arms (readable) */}
      <ArmsHeader count={cells.length} />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {cells.map((cell, i) => {
          const entries = Object.entries(cell.factorLevels);
          return (
            <div
              key={cell.cellId}
              className={`rounded-lg border p-2.5 text-[12.5px] ${
                cell.baseline ? "border-primary/45 bg-primary/8" : "border-outline/30 bg-surface/40"
              }`}
            >
              <div className="mb-1 flex items-center gap-1.5 font-semibold text-text-main">
                <Sym name={cell.baseline ? "flag" : "conversion_path"} size={14} />
                {!multiFactor && entries.length === 1 ? (
                  <>
                    {levelLabel[entries[0][0]]?.[entries[0][1]] ?? entries[0][1]}
                    {cell.baseline ? (
                      <span className="ml-1 text-[10.5px] font-medium uppercase tracking-wide text-primary">
                        {t("experiments.taskDetail.control")}
                      </span>
                    ) : null}
                  </>
                ) : (
                  <>
                    {cell.baseline
                      ? t("experiments.taskDetail.controlCombination")
                      : t("experiments.taskDetail.armLetter", {
                          letter: String.fromCharCode(65 + i),
                        })}
                  </>
                )}
              </div>
              {multiFactor || entries.length !== 1 ? (
                <div className="space-y-0.5 text-text-variant">
                  {entries.map(([fid, lid]) => (
                    <div key={fid}>
                      <span className="text-text-dim">{factorLabel[fid] ?? fid}:</span>{" "}
                      {levelLabel[fid]?.[lid] ?? lid}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </StudioGlassPanel>
  );
}

function PutDesignSection({ detail }: { detail: TaskDetail }) {
  const { t } = useI18n();
  const { factorLabel, levelLabel } = useLabelMaps(detail);
  const dim = detail.putDimension ?? "persona attribute";
  const values = detail.cohortStrategy.dimensionFilters?.[dim] ?? [];
  const env = detail.design.cells.find((c) => c.baseline) ?? detail.design.cells[0];
  return (
    <StudioGlassPanel className="p-4">
      <SectionHeader
        icon="groups"
        title={t("experiments.taskDetail.design")}
        hint={`${designLabel(detail.declaredDesignType, t)} · ${values.length || "?"} ${t("experiments.taskDetail.armsWord", { count: values.length })}`}
      />

      {/* Fixed environment */}
      {env ? (
        <div className="mb-3 rounded-lg border border-outline/30 bg-surface/40 p-2.5 text-[12px]">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-text-main">
            <Sym name="lock" size={13} className="text-text-dim" /> {t("experiments.taskDetail.environment")}
          </div>
          <div className="flex flex-wrap gap-1.5 text-text-variant">
            {Object.entries(env.factorLevels).map(([f, l]) => (
              <span key={f} className="rounded bg-surface-high/60 px-1.5 py-0.5">
                {factorLabel[f] ?? f}: {levelLabel[f]?.[l] ?? l}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {/* Contrast arms */}
      <ArmsHeader count={values.length} contrast />
      {values.length > 0 ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {values.map((v, i) => (
            <div
              key={v}
              className={`rounded-lg border p-2.5 text-[12.5px] ${
                i === 0 ? "border-secondary/45 bg-secondary/8" : "border-outline/30 bg-surface/40"
              }`}
            >
              <div className="flex items-center gap-1.5 font-semibold text-text-main">
                <Sym name={i === 0 ? "flag" : "conversion_path"} size={14} />
                {v}
                {i === 0 ? <span className="text-[11px] font-normal text-text-dim">· {t("experiments.taskDetail.reference")}</span> : null}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="rounded-md bg-warn/10 p-2 text-[12px] text-text-variant">
          {t("experiments.taskDetail.noValuesFor", { dim: humanizeToken(dim) })}
        </p>
      )}
    </StudioGlassPanel>
  );
}

function ArmsHeader({ count, contrast }: { count: number; contrast?: boolean }) {
  const { t } = useI18n();
  return (
    <div className="mb-1.5 flex items-center gap-2 text-[11.5px] text-text-dim">
      <span className="font-medium">{t("experiments.taskDetail.armsHeader", { count })}</span>
      <span className="ml-auto inline-flex items-center gap-1">
        <Sym name="flag" size={12} className={contrast ? "text-secondary" : "text-primary"} />
        {contrast ? t("experiments.taskDetail.reference") : t("experiments.taskDetail.control")}
      </span>
    </div>
  );
}

function strategyPortions(
  strategy: TaskDetail["cohortStrategy"],
): Record<string, Record<string, number>> | null {
  const raw = strategy.portions || strategy.sampling?.portions;
  if (!raw || Object.keys(raw).length === 0) return null;
  return raw;
}

function sharePercents(
  values: string[],
  weights: Record<string, number> | undefined,
): Record<string, number> {
  const w = values.map((v) => {
    const raw = weights?.[v];
    return typeof raw === "number" && raw > 0 ? raw : 0;
  });
  const total = w.reduce((sum, x) => sum + x, 0);
  const out: Record<string, number> = {};
  values.forEach((v, i) => {
    out[v] = total > 0 ? Math.round((100 * (w[i] ?? 0)) / total) : 0;
  });
  return out;
}

function CohortStrategyView({ strategy }: { strategy: TaskDetail["cohortStrategy"] }) {
  const { t } = useI18n();
  const sampling = strategy.sampling ?? {};
  const filters = Object.entries(strategy.dimensionFilters ?? {});
  const portions = strategyPortions(strategy);
  const sampleSize = sampling.sampleSize ?? sampling.size;
  return (
    <div className="space-y-2.5 text-[12.5px]">
      <Row k={t("experiments.taskDetail.pool")} v={strategy.pool ?? "—"} mono />
      {sampling.mode ? <Row k={t("experiments.taskDetail.sampling")} v={sampling.mode} /> : null}
      {sampling.allocation ? <Row k={t("experiments.taskDetail.allocation")} v={sampling.allocation} /> : null}
      {typeof sampleSize === "number" ? <Row k={t("experiments.taskDetail.size")} v={String(sampleSize)} /> : null}
      {typeof sampling.perCell === "number" ? <Row k={t("experiments.taskDetail.perCell")} v={String(sampling.perCell)} /> : null}
      {sampling.fields && sampling.fields.length > 0 ? (
        <div>
          <div className="mb-1 text-text-dim">{t("experiments.taskDetail.stratify")}</div>
          <div className="flex flex-wrap gap-1">
            {sampling.fields.map((f) => (
              <span key={f} className="rounded bg-surface-high/60 px-1.5 py-0.5 text-[11px]">
                {humanizeToken(f)}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {filters.length > 0 ? (
        <div className="border-t border-outline/20 pt-2">
          <div className="mb-1 text-text-dim">{t("experiments.taskDetail.filters")}</div>
          <div className="space-y-1.5">
            {filters.map(([dim, vals]) => {
              const dimWeights = portions?.[dim];
              const pct = dimWeights ? sharePercents(vals, dimWeights) : null;
              return (
                <div key={dim}>
                  <span className="text-[11px] text-text-variant">{humanizeToken(dim)}</span>
                  <div className="mt-0.5 flex flex-wrap gap-1">
                    {vals.map((v) => (
                      <span
                        key={v}
                        className="inline-flex items-center gap-1 rounded-full border border-outline/40 bg-surface-high/50 px-2 py-0.5 text-[11px] text-text-variant"
                      >
                        <span>{v}</span>
                        {pct && (pct[v] ?? 0) > 0 ? (
                          <span className="tabular-nums text-text-dim">{pct[v]}%</span>
                        ) : null}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-text-dim">{k}</span>
      <span className={`text-right font-medium text-text-main ${mono ? "font-mono text-[11.5px]" : ""}`}>
        {v}
      </span>
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
        className={`mb-2 flex w-full items-center gap-2 text-left ${FOCUS_RING}`}
      >
        <Sym name={open ? "expand_more" : "chevron_right"} size={18} className="text-text-dim" />
        <h3 className="font-display text-[14px] font-semibold text-text-main">{t("experiments.taskDetail.taskInstruction")}</h3>
      </button>
      {open ? (
        <div className="max-h-[420px] overflow-auto rounded-lg border border-outline/30 bg-surface/40 p-3">
          <Markdown className="text-[12.5px]">{markdown}</Markdown>
        </div>
      ) : null}
    </div>
  );
}
