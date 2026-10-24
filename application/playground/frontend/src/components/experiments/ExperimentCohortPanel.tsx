import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  ExperimentTaskDetail as TaskDetail,
  OverlayDimension,
  PersonaDatasetListResponse,
  PersonaPoolCatalog,
  PersonaPoolGenerateProgress,
  PersonaPoolSampleResult,
  PutContrastProgress,
} from "@/lib/types";
import { PERSONA_BENCH_POOL } from "@/lib/types";
import { FOCUS_RING, Sym, humanizeToken } from "../cockpit/cockpitShared";
import { CockpitSelect, type CockpitSelectOption } from "../cockpit/setup/CockpitSelect";
import {
  PersonaFilterModal,
  type PersonaMarginals,
} from "../cockpit/setup/PersonaFilterModal";
import {
  STUDY_OVERLAY_GROUP_ID,
  activeFilterCount,
  collectCatalogDimIds,
  emptyPersonaDimensionFilters,
  filterAxisIds,
  type PersonaDimensionFilters,
} from "../cockpit/setup/personaSamplingTypes";
import {
  useDimensionLabels,
  type DimensionLabelLookup,
} from "@/lib/dimensionLabels";
import { ArmCohortMap, errMessage, poolSlug } from "./experimentShared";
import { useI18n } from "@/i18n/I18nProvider";

type Translate = ReturnType<typeof useI18n>["t"];

/** Where the cohort comes from — the first-class choice. */
export type SutSource = "dataset" | "generate";
/** How to draw from an existing dataset. */
export type SutDrawMode = "strategy" | "custom";
/** How synthesize builds the cohort. */
export type SutSynthMode = "contract" | "custom";
/** How generate (and PUT draw / dataset custom) fills groups. */
export type GenMixMode = "random" | "perCell" | "proportional";

export interface SutCohortSpec {
  source: SutSource;
  pool: string;
  drawMode: SutDrawMode;
  /** Synthesize path: task contract vs custom mix. */
  synthMode: SutSynthMode;
  perArm: number;
  perCell: number;
  allocation: string;
  fields: string[];
  seed: number;
  count: number;
  /** Optional Task-plan size override; unset = use the task's authored size. */
  contractSize?: number;
  /** How to fill custom draw / synthesize. */
  genMode: GenMixMode;
  /** Dimension filters (narrow the dataset / constrain synthesis). */
  filters: PersonaDimensionFilters;
  /** Custom attributes that aren't in the schema — synthesized on the fly. */
  overlays: OverlayDimension[];
  /** Per-dim value weights for By share (generate · independentMarginal). */
  marginals: PersonaMarginals;
  /** Set once a synthesize run completes; the launch uses this pool. */
  generatedPool?: string;
  generatedIds?: string[];
  generatedLabel?: string;
}

export interface ContractGaps {
  missingDims: string[];
  missingValues: { dim: string; values: string[] }[];
}

export interface PutArmCohort {
  label: string;
  dimensionValue: string;
  personaIds: string[];
  personaPool: string;
  /** Set when this arm's tested value can't pass the persona DAG. */
  error?: string;
}

export interface PutCohortSpec {
  source: SutSource;
  pool: string;
  /** Synthesize path: task contract vs custom mix. */
  synthMode: SutSynthMode;
  /** N per arm when ``genMode`` is by cell. */
  perArm: number;
  /** Total N when ``genMode`` is random or by share. */
  count: number;
  /** Optional Task-plan size override; unset = use the task's authored size. */
  contractSize?: number;
  genMode: GenMixMode;
  seed: number;
  /** Contrast values in arm order; first is the reference. */
  values: string[];
  /** Extra eligibility (not the contrast dim — chips own that). */
  filters: PersonaDimensionFilters;
  overlays: OverlayDimension[];
  marginals: PersonaMarginals;
  /** Filled after Draw / Synthesize — one slice per selected value. */
  arms: PutArmCohort[] | null;
  generatedPool?: string;
  generatedLabel?: string;
}

const mixModes = (t: Translate): { id: GenMixMode; label: string; hint: string }[] => [
  {
    id: "random",
    label: t("experiments.cohort.mix.random.label"),
    hint: t("experiments.cohort.mix.random.hint"),
  },
  {
    id: "perCell",
    label: t("experiments.cohort.mix.perCell.label"),
    hint: t("experiments.cohort.mix.perCell.hint"),
  },
  {
    id: "proportional",
    label: t("experiments.cohort.mix.proportional.label"),
    hint: t("experiments.cohort.mix.proportional.hint"),
  },
];

const drawModes = (t: Translate): { id: SutDrawMode; label: string; icon: string }[] => [
  { id: "strategy", label: t("experiments.cohort.source.taskPlan"), icon: "playlist_add_check" },
  { id: "custom", label: t("experiments.cohort.source.custom"), icon: "tune" },
];

const synthModes = (
  t: Translate,
): { id: SutSynthMode; label: string; hint: string; icon: string }[] => [
  {
    id: "contract",
    label: t("experiments.cohort.source.taskPlan"),
    hint: t("experiments.cohort.synth.contract.hint"),
    icon: "playlist_add_check",
  },
  {
    id: "custom",
    label: t("experiments.cohort.source.custom"),
    hint: t("experiments.cohort.synth.custom.hint"),
    icon: "tune",
  },
];

/** Choice tiles: brand blue only on the selected fill; copy stays neutral. */
const CHOICE_IDLE =
  "border-outline/20 bg-surface-high/20 text-text-variant hover:border-outline/40 hover:bg-surface-high/40";
const CHOICE_ON = "border-primary/30 bg-primary/[0.08] text-text-main";

/** Flatten the modal-native filter shape into the API's dimensionFilters map. */
export function flattenFilters(filters: PersonaDimensionFilters): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [dim, values] of Object.entries(filters.dimensionFilters ?? {})) {
    if (values.length > 0) out[dim] = values;
  }
  return out;
}

/** Catalog dim → value set (schema / pool coverage). */
export function catalogDimValues(
  catalog: PersonaPoolCatalog | null | undefined,
): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  const add = (id: string, values: string[] | undefined) => {
    if (!out.has(id)) out.set(id, new Set());
    const set = out.get(id)!;
    for (const v of values ?? []) set.add(v);
  };
  for (const group of catalog?.dimensionCategories?.devProfile?.groups ?? []) {
    if (group.id === STUDY_OVERLAY_GROUP_ID) continue;
    for (const dim of group.dimensions ?? []) add(dim.id, dim.values);
    for (const sub of group.subgroups ?? []) {
      for (const dim of sub.dimensions ?? []) add(dim.id, dim.values);
    }
  }
  return out;
}

/**
 * Compare task ``persona_strategy`` dims/values against a pool catalog.
 * Missing dims or required values that the catalog cannot express are gaps.
 */
export function contractGaps(
  catalog: PersonaPoolCatalog | null | undefined,
  cohortStrategy: {
    dimensionFilters?: Record<string, string[]>;
    sampling?: { fields?: string[] };
  },
): ContractGaps {
  const filters = cohortStrategy.dimensionFilters ?? {};
  const fields = cohortStrategy.sampling?.fields ?? [];
  const dimIds = collectCatalogDimIds(catalog);
  const valuesByDim = catalogDimValues(catalog);
  const dimsToCheck = new Set([...Object.keys(filters), ...fields]);

  const missingDims: string[] = [];
  const missingValues: { dim: string; values: string[] }[] = [];

  for (const dim of dimsToCheck) {
    if (!dimIds.has(dim)) {
      missingDims.push(dim);
      continue;
    }
    const required = filters[dim] ?? [];
    if (required.length === 0) continue;
    const available = valuesByDim.get(dim) ?? new Set();
    const absent = required.filter((v) => !available.has(v));
    if (absent.length > 0) missingValues.push({ dim, values: absent });
  }
  return { missingDims, missingValues };
}

export function hasContractGaps(gaps: ContractGaps): boolean {
  return gaps.missingDims.length > 0 || gaps.missingValues.length > 0;
}

/** Gaps still open after overlay attrs cover missing dim ids. */
export function remainingContractGaps(
  gaps: ContractGaps,
  overlays: OverlayDimension[],
): ContractGaps {
  const covered = new Set(overlays.map((o) => o.id));
  return {
    missingDims: gaps.missingDims.filter((d) => !covered.has(d)),
    missingValues: gaps.missingValues.filter((mv) => !covered.has(mv.dim)),
  };
}

/** Drop taxonomy prefixes like ``big5_`` from raw ids when catalog label is missing. */
function humanizeDimId(dimId: string): string {
  const stripped = dimId.replace(
    /^(big5|mbti|hexaco|riasec|schwartz|ocean)_/i,
    "",
  );
  return humanizeToken(stripped || dimId);
}

function catalogDimDisplayLabel(
  catalog: PersonaPoolCatalog | null | undefined,
  dimId: string,
  labels: DimensionLabelLookup,
  overlays: OverlayDimension[] = [],
): string {
  const overlay = overlays.find((o) => o.id === dimId);
  if (overlay?.label?.trim()) {
    return labels.dimLabel(dimId, overlay.label.trim());
  }
  const groups = catalog?.dimensionCategories?.devProfile?.groups ?? [];
  for (const group of groups) {
    for (const dim of group.dimensions ?? []) {
      if (dim.id === dimId) {
        const base = (dim.label || humanizeDimId(dim.id)).trim();
        return labels.dimLabel(dim.id, base);
      }
    }
    for (const sub of group.subgroups ?? []) {
      for (const dim of sub.dimensions ?? []) {
        if (dim.id === dimId) {
          const base = (dim.label || humanizeDimId(dim.id)).trim();
          return labels.dimLabel(dim.id, base);
        }
      }
    }
  }
  return labels.dimLabel(dimId, humanizeDimId(dimId));
}

/** Axes for By cell / By share = dims the user picked values for in Who. */
export function mixAxesFromWho(
  filters: PersonaDimensionFilters,
  overlays: OverlayDimension[] = [],
): string[] {
  const ids = new Set(filterAxisIds(filters));
  for (const o of overlays) ids.add(o.id);
  return [...ids];
}

/** Merge overlay values into dimensionFilters (selected values, else full overlay). */
function filtersWithOverlays(
  filters: PersonaDimensionFilters,
  overlays: OverlayDimension[],
): Record<string, string[]> {
  const out = flattenFilters(filters);
  for (const o of overlays) {
    out[o.id] = filters.dimensionFilters[o.id]?.length
      ? filters.dimensionFilters[o.id]
      : [...o.values];
  }
  return out;
}

/**
 * PUT generate filters: Task plan uses the task cohort as-is; Custom uses extra Who.
 * Contrast chips always win for the measured dimension.
 */
export function putEligibilityFilters(args: {
  dimension: string;
  values: string[];
  synthMode: SutSynthMode;
  taskFilters: Record<string, string[]>;
  extraFilters: PersonaDimensionFilters;
  overlays: OverlayDimension[];
}): Record<string, string[]> {
  if (args.synthMode === "contract") {
    return {
      ...args.taskFilters,
      [args.dimension]: [...args.values],
    };
  }
  const extras = filtersWithOverlays(args.extraFilters, args.overlays);
  return {
    ...extras,
    [args.dimension]: [...args.values],
  };
}

function fillModeFromStrategy(sampling?: {
  mode?: string;
  allocation?: string;
}): GenMixMode {
  if (sampling?.mode === "random") return "random";
  if (
    sampling?.allocation === "proportional" ||
    sampling?.allocation === "independentMarginal"
  ) {
    return "proportional";
  }
  return "perCell";
}

function suggestedSynthCount(detail: TaskDetail): number {
  const filters = detail.cohortStrategy.dimensionFilters ?? {};
  const fields = detail.cohortStrategy.sampling?.fields ?? Object.keys(filters);
  const perCell = detail.cohortStrategy.sampling?.perCell ?? 1;
  const cells = fields.reduce((acc, f) => acc * Math.max(1, (filters[f] ?? []).length), 1);
  return Math.max(cells * Math.max(1, perCell), 8);
}

export function defaultSutSpec(detail: TaskDetail): SutCohortSpec {
  const s = detail.cohortStrategy.sampling ?? {};
  return {
    source: "dataset",
    // Dataset is chosen at run time — task strategy must not hard-require a pool.
    pool: detail.cohortStrategy.pool || "",
    drawMode: "strategy",
    synthMode: "contract",
    perArm: 0,
    perCell: typeof s.perCell === "number" ? s.perCell : 2,
    allocation: s.allocation || "perCell",
    fields: s.fields && s.fields.length > 0 ? [...s.fields] : [],
    seed: 42,
    count: suggestedSynthCount(detail),
    genMode: "perCell",
    filters: emptyPersonaDimensionFilters(),
    overlays: [],
    marginals: {},
  };
}

export function putDimensionId(detail: TaskDetail): string {
  return (
    detail.putDimension ||
    Object.keys(detail.cohortStrategy.dimensionFilters ?? {})[0] ||
    ""
  );
}

export function defaultPutSpec(detail: TaskDetail): PutCohortSpec {
  const dim = putDimensionId(detail);
  const values = dim ? [...(detail.cohortStrategy.dimensionFilters?.[dim] ?? [])] : [];
  const perCell = detail.cohortStrategy.sampling?.perCell;
  const perArm = typeof perCell === "number" ? perCell : 12;
  return {
    source: "dataset",
    pool: detail.cohortStrategy.pool || "",
    synthMode: "contract",
    perArm,
    count: Math.max(perArm * Math.max(values.length, 2), 8),
    genMode: "perCell",
    seed: 42,
    values,
    filters: emptyPersonaDimensionFilters(),
    overlays: [],
    marginals: {},
    arms: null,
  };
}

/** PUT is ready once each selected contrast value has a non-empty cohort slice. */
export function putCohortReady(spec: PutCohortSpec): boolean {
  if (!spec.arms || spec.arms.length < 2) return false;
  if (spec.arms.length !== spec.values.length) return false;
  return spec.arms.every(
    (arm, i) => arm.dimensionValue === spec.values[i] && arm.personaIds.length > 0,
  );
}

/** SUT is ready to launch once the chosen source has enough to draw a cohort. */
export function sutCohortReady(
  spec: SutCohortSpec,
  opts?: { hasContractGaps?: boolean },
): boolean {
  if (spec.source === "generate") {
    return Boolean(spec.generatedPool && spec.generatedIds?.length);
  }
  if (!spec.pool) return false;
  if (spec.drawMode === "strategy") {
    return !opts?.hasContractGaps;
  }
  // custom mix — axes come from Who selections, not a separate stratify list
  const axes = mixAxesFromWho(spec.filters, spec.overlays);
  if (spec.genMode === "random") return spec.count > 0 || spec.perArm > 0;
  if (spec.genMode === "perCell") return axes.length > 0 && spec.perCell > 0;
  return axes.length > 0 && spec.count > 0;
}

/**
 * Cohort panel for System-Under-Test runs. One cohort runs across every arm, so
 * there is no per-arm contrast — just where the cohort comes from. Source is the
 * first-class decision: draw from an existing dataset, or synthesize a fresh one.
 * Dimension filters and custom attributes refine either path.
 */
export function SutCohortPanel({
  detail,
  value,
  onChange,
}: {
  detail: TaskDetail;
  value: SutCohortSpec;
  onChange: (next: SutCohortSpec) => void;
}) {
  const datasetsQuery = useQuery<PersonaDatasetListResponse>({
    queryKey: ["persona-datasets"],
    queryFn: api.listPersonaDatasets,
  });
  const catalogQuery = useQuery<PersonaPoolCatalog>({
    queryKey: ["persona-pool-catalog", value.pool],
    queryFn: () => api.getPersonaPoolCatalog(value.pool || undefined),
    staleTime: 60_000,
  });
  const { t } = useI18n();
  const [filterOpen, setFilterOpen] = useState(false);
  const set = (patch: Partial<SutCohortSpec>) => onChange({ ...value, ...patch });
  const dimLabels = useDimensionLabels();
  const catalog = catalogQuery.data ?? null;
  const dimName = (id: string) =>
    catalogDimDisplayLabel(catalog, id, dimLabels, value.overlays);

  const poolOptions = datasetsQuery.data?.datasets ?? [];
  const datasetSelectOptions = useMemo<CockpitSelectOption[]>(() => {
    const options: CockpitSelectOption[] = poolOptions.map((p) => ({
      value: p.pool,
      label: p.label,
      meta:
        typeof p.count === "number"
          ? t("experiments.cohort.personaCount", { count: p.count })
          : undefined,
    }));
    if (value.pool && !options.some((o) => o.value === value.pool)) {
      const slug = value.pool.split("/").filter(Boolean).pop() || value.pool;
      options.unshift({
        value: value.pool,
        label: slug,
        meta: t("experiments.cohort.taskDefault"),
      });
    }
    return options;
  }, [poolOptions, value.pool, t]);
  const strategyFields = detail.cohortStrategy.sampling?.fields ?? [];
  const availableFields =
    strategyFields.length > 0
      ? strategyFields
      : Object.keys(detail.cohortStrategy.dimensionFilters ?? {});
  const strategyFilters = detail.cohortStrategy.dimensionFilters ?? {};
  const strategyPerCell = detail.cohortStrategy.sampling?.perCell ?? 1;
  const strategyFill = fillModeFromStrategy(detail.cohortStrategy.sampling);
  const strategyPortions =
    detail.cohortStrategy.portions ||
    detail.cohortStrategy.sampling?.portions ||
    null;
  const authoredSize =
    detail.cohortStrategy.sampling?.sampleSize ?? detail.cohortStrategy.sampling?.size;
  const strategyExpectedN =
    strategyFill === "perCell"
      ? Math.max(
          1,
          availableFields.reduce(
            (acc, f) => acc * Math.max(1, (strategyFilters[f] ?? []).length),
            1,
          ) * Math.max(1, strategyPerCell),
        )
      : Math.max(1, typeof authoredSize === "number" ? authoredSize : 8);

  const gaps = useMemo(() => {
    if (!value.pool || !catalogQuery.data) {
      return { missingDims: [] as string[], missingValues: [] as { dim: string; values: string[] }[] };
    }
    return contractGaps(catalogQuery.data, detail.cohortStrategy);
  }, [value.pool, catalogQuery.data, detail.cohortStrategy]);
  const poolHasGaps = hasContractGaps(gaps);

  const switchToSynthesize = () =>
    set({
      source: "generate",
      synthMode: "contract",
      generatedPool: undefined,
      generatedIds: undefined,
      generatedLabel: undefined,
      // Don't carry dataset/strategy Who into synthesize; Custom starts empty.
      fields: [],
      filters: emptyPersonaDimensionFilters(),
      overlays: [],
      marginals: {},
    });

  return (
    <div className="space-y-2">
      <div>
        <FieldLabel icon="dataset" text={t("experiments.cohort.source.label")} />
        <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
          <SourceCard
            active={value.source === "dataset"}
            onClick={() => set({ source: "dataset" })}
            icon="dataset"
            title={t("experiments.cohort.source.dataset.title")}
            desc={t("experiments.cohort.source.dataset.desc")}
          />
          <SourceCard
            active={value.source === "generate"}
            onClick={switchToSynthesize}
            icon="auto_awesome"
            title={t("experiments.cohort.source.generate.title")}
            desc={t("experiments.cohort.source.generate.desc")}
          />
        </div>
      </div>

      {value.source === "dataset" ? (
        <div className="space-y-2.5">
          <div className="w-full max-w-3xl">
            <CockpitSelect
              label={t("experiments.cohort.dataset.label")}
              value={value.pool}
              options={datasetSelectOptions}
              onChange={(pool) => set({ pool })}
              inlineLabel
              wideMenu
              wrapOptions
              showSelectedMeta={false}
            />
          </div>

          {value.pool && poolHasGaps ? (
            <div
              className="rounded-lg border border-danger/35 bg-danger/[0.07] p-3 text-[12.5px]"
              role="status"
            >
              <div className="flex items-start gap-2">
                <Sym name="warning" size={16} className="mt-0.5 shrink-0 text-danger" />
                <div className="min-w-0 flex-1 space-y-2">
                  <p className="font-medium text-text-main">
                    {t("experiments.cohort.gapWarning.title")}
                  </p>
                  <GapChips gaps={gaps} catalog={catalog} />
                  <button
                    type="button"
                    onClick={switchToSynthesize}
                    className={`inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12px] font-semibold text-on-primary transition hover:bg-primary-dim ${FOCUS_RING}`}
                  >
                    <Sym name="auto_awesome" size={14} fill={1} />
                    {t("experiments.cohort.gapWarning.action")}
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          <SegmentedChoice
            label={t("experiments.cohort.howToDraw")}
            icon="tune"
            value={value.drawMode}
            options={drawModes(t)}
            onChange={(drawMode) => {
              if (drawMode === value.drawMode) return;
              set({
                drawMode,
                ...(drawMode === "custom"
                  ? {
                      fields: [],
                      filters: emptyPersonaDimensionFilters(),
                      overlays: [],
                      marginals: {},
                    }
                  : {}),
              });
            }}
          />

          <div className="rounded-lg bg-surface-lowest/55 p-3">
            {value.drawMode === "strategy" ? (
              <div className="space-y-2 text-[12.5px]">
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
                  <span>
                    <span className="text-text-dim">{t("experiments.cohort.stat.people")} </span>
                    <span className="font-semibold tabular-nums text-text-main">
                      {strategyExpectedN}
                    </span>
                  </span>
                  <span>
                    <span className="text-text-dim">{t("experiments.cohort.stat.mix")} </span>
                    <span className="text-text-variant">
                      {strategyFill === "perCell"
                        ? t("experiments.cohort.perGroup", { count: strategyPerCell })
                        : strategyFill === "proportional"
                          ? t("experiments.cohort.mix.proportional.label")
                          : t("experiments.cohort.mix.random.label")}
                    </span>
                  </span>
                  {availableFields.length > 0 ? (
                    <span className="min-w-0">
                      <span className="text-text-dim">{t("experiments.cohort.stat.groups")} </span>
                      <span className="text-text-variant">
                        {availableFields.map((f) => dimName(f)).join(" × ")}
                      </span>
                    </span>
                  ) : null}
                </div>
                <CohortComposition
                  filters={strategyFilters}
                  portions={strategyPortions}
                  fields={availableFields}
                  fill={strategyFill}
                  dimName={dimName}
                  valueLabel={(dim, v) => dimLabels.valueLabel(dim, v)}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <label className="text-text-dim">{t("experiments.cohort.cohortSize")}</label>
                  <input
                    type="number"
                    min={0}
                    value={value.perArm || ""}
                    placeholder={String(strategyExpectedN)}
                    onChange={(e) => set({ perArm: Math.max(0, Number(e.target.value) || 0) })}
                    className={`w-24 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                  />
                  <span className="text-[11px] text-text-dim">{t("experiments.cohort.optionalOverride")}</span>
                  <label className="ml-1 inline-flex items-center gap-1.5 text-text-dim">
                    {t("experiments.cohort.seed")}
                    <input
                      type="number"
                      value={value.seed}
                      onChange={(e) => set({ seed: Number(e.target.value) || 0 })}
                      className={`w-[4.5rem] rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                    />
                  </label>
                </div>
                {poolHasGaps ? (
                  <span className="block text-[11.5px] text-danger">
                    {t("experiments.cohort.gapSwitchHint")}
                  </span>
                ) : null}
              </div>
            ) : (
              <div className="space-y-2.5 text-[12.5px]">
                <MixModePicker
                  value={value.genMode}
                  onChange={(genMode) => set({ genMode })}
                />
                {value.genMode === "perCell" ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="text-text-dim">{t("experiments.cohort.peoplePerGroup")}</label>
                    <input
                      type="number"
                      min={1}
                      value={value.perCell || ""}
                      onChange={(e) => set({ perCell: Math.max(1, Number(e.target.value) || 1) })}
                      className={`w-24 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                    />
                    <label className="inline-flex items-center gap-1.5 text-text-dim">
                      {t("experiments.cohort.seed")}
                      <input
                        type="number"
                        value={value.seed}
                        onChange={(e) => set({ seed: Number(e.target.value) || 0 })}
                        className={`w-[4.5rem] rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                      />
                    </label>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="text-text-dim">{t("experiments.cohort.totalPeople")}</label>
                    <input
                      type="number"
                      min={1}
                      value={value.count || value.perArm || ""}
                      onChange={(e) => {
                        const n = Math.max(1, Number(e.target.value) || 1);
                        set({ count: n, perArm: n });
                      }}
                      className={`w-24 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                    />
                    <label className="inline-flex items-center gap-1.5 text-text-dim">
                      {t("experiments.cohort.seed")}
                      <input
                        type="number"
                        value={value.seed}
                        onChange={(e) => set({ seed: Number(e.target.value) || 0 })}
                        className={`w-[4.5rem] rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                      />
                    </label>
                  </div>
                )}
                {(() => {
                  const axes = mixAxesFromWho(value.filters, value.overlays);
                  if (axes.length > 0) return null;
                  return (
                    <p className="text-[11.5px] text-text-dim">
                      {value.genMode === "random"
                        ? t("experiments.cohort.hint.addWhoRandom")
                        : value.genMode === "perCell"
                          ? t("experiments.cohort.hint.chooseWhoPerCell")
                          : t("experiments.cohort.hint.chooseWhoShare")}
                    </p>
                  );
                })()}
              </div>
            )}
          </div>

          {value.drawMode === "custom" ? (
            <WhoSummary
              spec={value}
              applies
              whoLabel={t("experiments.cohort.whoEligible")}
              catalog={catalogQuery.data ?? null}
              onOpen={() => setFilterOpen(true)}
              onClearFilters={() => set({ filters: emptyPersonaDimensionFilters() })}
              onClearOverlays={() => set({ overlays: [] })}
            />
          ) : null}
        </div>
      ) : (
        <SynthesizePanel
          detail={detail}
          value={value}
          onChange={onChange}
          availableFields={availableFields}
          catalog={catalogQuery.data ?? null}
          onOpenSpec={() => setFilterOpen(true)}
        />
      )}

      <PersonaFilterModal
        open={filterOpen}
        catalog={catalogQuery.data ?? null}
        filters={value.filters}
        stratifyMode={false}
        fields={value.fields}
        onFieldsChange={(fields) => set({ fields })}
        showMarginals={
          value.source === "generate" &&
          value.synthMode === "custom" &&
          value.genMode === "proportional"
        }
        marginals={value.marginals}
        allowOverlayEdit={value.source === "generate"}
        showSelectedPane={false}
        overlayDimensions={value.source === "generate" ? value.overlays : undefined}
        onClose={() => setFilterOpen(false)}
        onConfirm={(next, nextMarginals, nextOverlay) => {
          const axes = mixAxesFromWho(
            next,
            value.source === "generate" && nextOverlay !== undefined
              ? nextOverlay
              : value.overlays,
          );
          const patch: Partial<SutCohortSpec> = {
            filters: next,
            fields: axes,
          };
          if (nextMarginals !== undefined) {
            patch.marginals = nextMarginals;
          }
          if (value.source === "generate" && nextOverlay !== undefined) {
            patch.overlays = nextOverlay;
          }
          set(patch);
        }}
      />
    </div>
  );
}

function SourceCard({
  active,
  onClick,
  icon,
  title,
  desc,
}: {
  active: boolean;
  onClick: () => void;
  icon: string;
  title: string;
  desc: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-left transition ${FOCUS_RING} ${
        active ? CHOICE_ON : CHOICE_IDLE
      }`}
    >
      <span
        className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md ${
          active ? "bg-primary/15 text-primary" : "bg-surface-high/60 text-text-dim"
        }`}
      >
        <Sym name={icon} size={16} fill={active ? 1 : 0} />
      </span>
      <span className="min-w-0">
        <span className="block text-[12.5px] font-semibold leading-snug text-text-main">
          {title}
        </span>
        <span className="mt-0.5 block text-[11px] leading-snug text-text-dim">{desc}</span>
      </span>
    </button>
  );
}

function SegmentedChoice<T extends string>({
  label,
  icon = "tune",
  value,
  options,
  onChange,
}: {
  label?: string;
  icon?: string;
  value: T;
  options: { id: T; label: string; hint?: string }[];
  onChange: (id: T) => void;
}) {
  const cols = options.length === 3 ? "grid-cols-3" : "grid-cols-2";
  return (
    <div>
      {label ? <FieldLabel icon={icon} text={label} /> : null}
      <div className={`grid ${cols} gap-0.5 rounded-lg bg-surface-lowest/80 p-0.5`}>
        {options.map((m) => {
          const active = value === m.id;
          return (
            <button
              key={m.id}
              type="button"
              title={m.hint}
              aria-pressed={active}
              onClick={() => onChange(m.id)}
              className={`rounded-md px-2 py-1.5 text-[11.5px] font-medium transition ${FOCUS_RING} ${
                active
                  ? "bg-primary text-on-primary"
                  : "text-text-variant hover:bg-surface-high/50 hover:text-text-main"
              }`}
            >
              {m.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function MixModePicker({
  value,
  onChange,
}: {
  value: GenMixMode;
  onChange: (mode: GenMixMode) => void;
}) {
  const { t } = useI18n();
  return (
    <SegmentedChoice
      label={t("experiments.cohort.stat.mix")}
      icon="tune"
      value={value}
      options={mixModes(t)}
      onChange={onChange}
    />
  );
}

/** Format By-share weights as display percentages (equal weight → even split). */
function sharePctMap(
  values: string[],
  weights: Record<string, number> | undefined,
): Record<string, number> {
  const w = values.map((v) => {
    const raw = weights?.[v];
    return typeof raw === "number" && raw >= 0 ? raw : 1;
  });
  const total = w.reduce((s, x) => s + x, 0);
  const out: Record<string, number> = {};
  values.forEach((v, i) => {
    out[v] = total > 0 ? Math.round((100 * (w[i] ?? 1)) / total) : 0;
  });
  return out;
}

/** Chart ramp used on scorecards — primary / violet / mint / amber. */
const SHARE_BAR_TONES = [
  "bg-primary",
  "bg-accent",
  "bg-secondary",
  "bg-warn",
  "bg-primary-dim",
  "bg-outline",
] as const;

/** Compact segmented bar + legend for value mixes.
 *  With ``even`` (or no ``pct``): equal-width segments, percentages hidden —
 *  used for eligibility-only dims whose mix is not constrained. */
function ShareValueBars({
  values,
  pct,
  labelFor,
  even,
}: {
  values: string[];
  pct?: Record<string, number>;
  labelFor: (value: string) => string;
  even?: boolean;
}) {
  const tones = SHARE_BAR_TONES;
  const eq = values.length > 0 ? 100 / values.length : 0;
  const showPct = !even && !!pct;
  const widthOf = (v: string) => (showPct ? (pct?.[v] ?? 0) : eq);
  const legend = (v: string) =>
    showPct ? `${labelFor(v)} ${pct?.[v] ?? 0}%` : labelFor(v);
  return (
    <div className="mt-1 space-y-1">
      <div
        className="flex h-2 w-full overflow-hidden rounded-full bg-surface-high/80"
        title={values.map(legend).join(" · ")}
        role="img"
        aria-label={values.map(legend).join(", ")}
      >
        {values.map((v, i) => {
          const w = widthOf(v);
          if (w <= 0) return null;
          return (
            <span
              key={v}
              className={`h-full ${tones[i % tones.length]}`}
              style={{ width: `${w}%` }}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-2.5 gap-y-0.5">
        {values.map((v, i) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 text-[10.5px] text-text-variant"
          >
            <span
              className={`h-1.5 w-1.5 shrink-0 rounded-sm ${tones[i % tones.length]}`}
              aria-hidden
            />
            <span>{labelFor(v)}</span>
            {showPct ? (
              <span className="tabular-nums text-text-dim">{pct?.[v] ?? 0}%</span>
            ) : null}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Per-dimension attribute composition preview for a cohort contract.
 *  Weighted stratify dims render target shares (%); eligibility-only dims
 *  render an even bar (mix not constrained — pool-driven / independent). */
function CohortComposition({
  filters,
  portions,
  fields,
  fill,
  dimName,
  valueLabel,
}: {
  filters: Record<string, string[]>;
  portions?: Record<string, Record<string, number>> | null;
  fields: string[];
  fill: string;
  dimName: (id: string) => string;
  valueLabel: (dim: string, value: string) => string;
}) {
  const { t } = useI18n();
  const order: string[] = [];
  for (const f of fields) {
    if ((filters[f]?.length ?? 0) > 0 && !order.includes(f)) order.push(f);
  }
  for (const d of Object.keys(filters)) {
    if ((filters[d]?.length ?? 0) > 0 && !order.includes(d)) order.push(d);
  }
  if (order.length === 0) return null;
  return (
    <div className="mt-2 space-y-2 border-t border-outline/20 pt-2">
      <p className="text-[10.5px] font-semibold uppercase tracking-wide text-text-dim">
        {t("experiments.cohort.composition")}
      </p>
      {order.map((dim) => {
        const values = filters[dim] ?? [];
        const weights = portions?.[dim];
        const weighted =
          fill === "proportional" &&
          !!weights &&
          Object.keys(weights).length > 0;
        return (
          <div key={dim}>
            <p className="text-[12px] font-medium text-text-main">
              {dimName(dim)}
              {weighted ? null : (
                <span className="ml-1 font-normal text-text-dim">· {t("experiments.cohort.even")}</span>
              )}
            </p>
            <ShareValueBars
              values={values}
              pct={weighted ? sharePctMap(values, weights) : undefined}
              even={!weighted}
              labelFor={(v) => valueLabel(dim, v)}
            />
          </div>
        );
      })}
    </div>
  );
}

type WhoSpecSlice = {
  source: SutSource;
  synthMode?: SutSynthMode;
  drawMode?: SutDrawMode;
  genMode: GenMixMode;
  filters: PersonaDimensionFilters;
  overlays: OverlayDimension[];
  marginals: PersonaMarginals;
};

/** Compact who/filters: Dimensions vs custom attributes; By-share shows %. */
function WhoSummary({
  spec,
  applies,
  onOpen,
  onClearFilters,
  onClearOverlays,
  whoLabel,
  catalog,
  emptyHint,
  showShare,
}: {
  spec: WhoSpecSlice;
  applies: boolean;
  onOpen: () => void;
  onClearFilters: () => void;
  onClearOverlays: () => void;
  whoLabel?: string;
  catalog?: PersonaPoolCatalog | null;
  emptyHint?: string;
  showShare?: boolean;
}) {
  const { t } = useI18n();
  const labels = useDimensionLabels();
  const compose = spec.source === "generate";
  const filterCount = activeFilterCount(spec.filters);
  const overlayCount = compose ? spec.overlays.length : 0;
  const dims = Object.entries(spec.filters.dimensionFilters ?? {}).filter(
    ([, v]) => v.length > 0,
  );
  const shareOn =
    showShare ??
    (spec.genMode === "proportional" &&
      (compose ? spec.synthMode === "custom" : spec.drawMode === "custom") &&
      (dims.length > 0 || overlayCount > 0));
  const empty =
    emptyHint ??
    (compose
      ? t("experiments.cohort.who.emptyCompose")
      : t("experiments.cohort.who.emptyDataset"));
  const title =
    whoLabel ??
    (compose
      ? t("experiments.cohort.whoGenerate")
      : t("experiments.cohort.whoEligible"));

  return (
    <div className="rounded-lg bg-surface-lowest/55 px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <FieldLabel icon={compose ? "auto_awesome" : "group"} text={title} />
        <button
          type="button"
          onClick={onOpen}
          disabled={!applies}
          className={`inline-flex items-center gap-1.5 rounded-md border border-outline/40 bg-surface-high/50 px-2.5 py-1 text-[12px] font-medium text-text-variant transition hover:border-outline/70 hover:text-text-main disabled:cursor-not-allowed disabled:opacity-45 ${FOCUS_RING}`}
        >
          <Sym name="tune" size={14} />
          {filterCount + overlayCount > 0
            ? t("experiments.cohort.edit")
            : t("experiments.cohort.add")}
        </button>
      </div>

      {filterCount + overlayCount === 0 ? (
        <p className="mt-0.5 text-[11.5px] text-text-dim">{empty}</p>
      ) : (
        <div className="mt-1.5 space-y-2">
          {dims.length > 0 ? (
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10.5px] font-semibold uppercase tracking-wide text-text-dim">
                  {t("experiments.cohort.dimensions")}
                </p>
                <button
                  type="button"
                  onClick={onClearFilters}
                  className={`text-[11px] text-text-dim hover:text-text-main ${FOCUS_RING} rounded`}
                >
                  {t("experiments.cohort.clear")}
                </button>
              </div>
              <ul className="divide-y divide-outline/15">
                {dims.map(([dim, values]) => {
                  const pct = shareOn
                    ? sharePctMap(values, spec.marginals[dim])
                    : null;
                  return (
                    <li key={dim} className="py-1.5 first:pt-0 last:pb-0">
                      <p className="text-[12px] font-medium text-text-main">
                        {catalogDimDisplayLabel(
                          catalog,
                          dim,
                          labels,
                          spec.overlays,
                        )}
                      </p>
                      {pct ? (
                        <ShareValueBars
                          values={values}
                          pct={pct}
                          labelFor={(v) => labels.valueLabel(dim, v)}
                        />
                      ) : (
                        <p className="mt-0.5 text-[11px] leading-snug text-text-variant">
                          <span className="text-text-dim">{t("experiments.cohort.values")} · </span>
                          {values
                            .map((v) => labels.valueLabel(dim, v))
                            .join(" · ")}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}

          {overlayCount > 0 ? (
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10.5px] font-semibold uppercase tracking-wide text-text-dim">
                  {t("experiments.cohort.attributes")}
                </p>
                <button
                  type="button"
                  onClick={onClearOverlays}
                  className={`text-[11px] text-text-dim hover:text-text-main ${FOCUS_RING} rounded`}
                >
                  {t("experiments.cohort.clear")}
                </button>
              </div>
              <ul className="divide-y divide-outline/15">
                {spec.overlays.map((o) => {
                  const pct = shareOn
                    ? sharePctMap(o.values, spec.marginals[o.id])
                    : null;
                  return (
                    <li key={o.id} className="py-1.5 first:pt-0 last:pb-0">
                      <p className="inline-flex items-center gap-1 text-[12px] font-medium text-text-main">
                        <Sym name="auto_awesome" size={11} />
                        {o.label || humanizeDimId(o.id)}
                        <span className="font-normal text-text-dim">· {t("experiments.cohort.custom")}</span>
                      </p>
                      {pct ? (
                        <ShareValueBars
                          values={o.values}
                          pct={pct}
                          labelFor={(v) => labels.valueLabel(o.id, v)}
                        />
                      ) : (
                        <p className="mt-0.5 text-[11px] leading-snug text-text-variant">
                          <span className="text-text-dim">{t("experiments.cohort.values")} · </span>
                          {o.values
                            .map((v) => labels.valueLabel(o.id, v))
                            .join(" · ")}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

/** Compact By-share plan for the post-generate result strip. */
function MixShareSummary({
  filters,
  overlays,
  marginals,
  catalog,
}: {
  filters: PersonaDimensionFilters;
  overlays: OverlayDimension[];
  marginals: PersonaMarginals;
  catalog?: PersonaPoolCatalog | null;
}) {
  const { t } = useI18n();
  const labels = useDimensionLabels();
  const dims = Object.entries(filters.dimensionFilters ?? {}).filter(
    ([, v]) => v.length > 0,
  );
  if (dims.length === 0 && overlays.length === 0) return null;
  return (
    <div className="rounded-md bg-surface-lowest/55 px-2.5 py-2 text-[11.5px]">
      <p className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-text-dim">
        {t("experiments.cohort.stat.mix")} · {t("experiments.cohort.mix.proportional.label")}
      </p>
      <ul className="space-y-2">
        {dims.map(([dim, values]) => {
          const pct = sharePctMap(values, marginals[dim]);
          return (
            <li key={dim}>
              <p className="font-medium text-text-main">
                {catalogDimDisplayLabel(catalog, dim, labels, overlays)}
              </p>
              <ShareValueBars
                values={values}
                pct={pct}
                labelFor={(v) => labels.valueLabel(dim, v)}
              />
            </li>
          );
        })}
        {overlays.map((o) => {
          const pct = sharePctMap(o.values, marginals[o.id]);
          return (
            <li key={o.id}>
              <p className="font-medium text-text-main">
                {o.label || humanizeDimId(o.id)}
                <span className="font-normal text-text-dim"> · {t("experiments.cohort.attr")}</span>
              </p>
              <ShareValueBars
                values={o.values}
                pct={pct}
                labelFor={(v) => labels.valueLabel(o.id, v)}
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function GapChips({
  gaps,
  catalog,
}: {
  gaps: ContractGaps;
  catalog?: PersonaPoolCatalog | null;
}) {
  const { t } = useI18n();
  const labels = useDimensionLabels();
  return (
    <div className="flex flex-wrap gap-1.5">
      {gaps.missingDims.map((dim) => (
        <span
          key={dim}
          className="rounded-full border border-danger/40 bg-danger/10 px-2.5 py-0.5 text-[11px] text-danger"
        >
          {t("experiments.cohort.gap.missingDim")} · {catalogDimDisplayLabel(catalog, dim, labels)}
        </span>
      ))}
      {gaps.missingValues.map((mv) => (
        <span
          key={mv.dim}
          className="rounded-full border border-danger/40 bg-danger/10 px-2.5 py-0.5 text-[11px] text-danger"
        >
          {catalogDimDisplayLabel(catalog, mv.dim, labels)} ·{" "}
          {mv.values.length > 2
            ? t("experiments.cohort.gap.missingValuesCount", { count: mv.values.length })
            : t("experiments.cohort.gap.missingValuesList", {
                values: mv.values.map((v) => labels.valueLabel(mv.dim, v)).join(", "),
              })}
        </span>
      ))}
    </div>
  );
}

function SynthesizePanel({
  detail,
  value,
  onChange,
  availableFields,
  catalog,
  onOpenSpec,
}: {
  detail: TaskDetail;
  value: SutCohortSpec;
  onChange: (next: SutCohortSpec) => void;
  availableFields: string[];
  catalog: PersonaPoolCatalog | null;
  onOpenSpec: () => void;
}) {
  const { t } = useI18n();
  const [progress, setProgress] = useState<PersonaPoolGenerateProgress | null>(null);
  const dimLabels = useDimensionLabels();
  const dimName = (id: string) =>
    catalogDimDisplayLabel(catalog, id, dimLabels, value.overlays);
  const taskFilters = detail.cohortStrategy.dimensionFilters ?? {};
  const userFilters = flattenFilters(value.filters);
  const effectiveFilters = { ...taskFilters, ...userFilters };
  const synthMode = value.synthMode ?? "contract";
  const mix = value.genMode ?? "perCell";

  const schemaGaps = useMemo(
    () => remainingContractGaps(contractGaps(catalog, detail.cohortStrategy), value.overlays),
    [catalog, detail.cohortStrategy, value.overlays],
  );
  const showSchemaGaps = synthMode === "contract" && hasContractGaps(schemaGaps);
  const hasExtraWho =
    activeFilterCount(value.filters) > 0 || value.overlays.length > 0;
  /** Contract already defines who — only open selection for gaps / extras. */
  const showContractWho = showSchemaGaps || hasExtraWho;

  const contractFields =
    availableFields.length > 0 ? availableFields : Object.keys(taskFilters);
  const strategyPerCell = detail.cohortStrategy.sampling?.perCell ?? 1;
  const strategyAllocation =
    detail.cohortStrategy.sampling?.allocation || "perCell";
  const authoredSize =
    detail.cohortStrategy.sampling?.sampleSize ?? detail.cohortStrategy.sampling?.size;
  const contractCombos = contractFields.reduce(
    (acc, f) => acc * Math.max(1, (taskFilters[f] ?? []).length),
    1,
  );
  const fill = fillModeFromStrategy(detail.cohortStrategy.sampling);
  const strategyPortions =
    detail.cohortStrategy.portions ||
    detail.cohortStrategy.sampling?.portions ||
    null;
  const contractN =
    fill === "perCell"
      ? Math.max(1, contractCombos * Math.max(1, strategyPerCell))
      : Math.max(1, typeof authoredSize === "number" ? authoredSize : 8);
  // Size is an optional operator override; per-cell fill derives N from the
  // groups × per-group count, so only share/random totals are editable here.
  const sizeEditable = fill !== "perCell";
  const effectiveContractN = value.contractSize ?? contractN;
  const sizeOverridden = value.contractSize != null && value.contractSize !== contractN;

  const customFields = mixAxesFromWho(value.filters, value.overlays);
  const customFilterMap = filtersWithOverlays(value.filters, value.overlays);
  const customCombos = customFields.reduce(
    (acc, f) => acc * Math.max(1, (customFilterMap[f] ?? []).length),
    1,
  );

  const genMutation = useMutation({
    mutationFn: async () => {
      setProgress(null);
      if (synthMode === "contract") {
        return api.generatePersonaPool(
          {
            taskPath: detail.task,
            seed: value.seed,
            dimensionFilters: effectiveFilters,
            overlayDimensions: value.overlays.length > 0 ? value.overlays : undefined,
            fields: contractFields,
            perCell: strategyPerCell,
            allocation: strategyAllocation,
            ...(value.contractSize != null ? { sampleSize: value.contractSize } : {}),
          },
          { onProgress: setProgress },
        );
      }
      const dimensionFilters =
        Object.keys(customFilterMap).length > 0 ? customFilterMap : undefined;
      return api.generatePersonaPool(
        {
          taskPath: detail.task,
          seed: value.seed,
          dimensionFilters,
          overlayDimensions: value.overlays.length > 0 ? value.overlays : undefined,
          ...(mix === "random"
            ? { count: value.count }
            : mix === "perCell"
              ? {
                  fields: customFields,
                  perCell: value.perCell,
                  allocation: "perCell",
                }
              : {
                  fields: customFields,
                  sampleSize: value.count,
                  allocation: "independentMarginal",
                  marginals: value.marginals,
                }),
        },
        { onProgress: setProgress },
      );
    },
    onSuccess: (result) => {
      onChange({
        ...value,
        generatedPool: result.pool,
        generatedIds: result.personaIds,
        generatedLabel: `${result.label} · ${result.count}`,
      });
    },
  });

  const seedField = (
    <label className="inline-flex items-center gap-1.5 text-[12px] text-text-dim">
      {t("experiments.cohort.seed")}
      <input
        type="number"
        value={value.seed}
        onChange={(e) => onChange({ ...value, seed: Number(e.target.value) || 0 })}
        className={`w-[4.5rem] rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
      />
    </label>
  );

  const synthButton = (
    <button
      type="button"
      onClick={() => genMutation.mutate()}
      disabled={genMutation.isPending}
      className={`inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-semibold text-on-primary transition hover:bg-primary-dim disabled:opacity-50 ${FOCUS_RING}`}
    >
      <Sym name="auto_awesome" size={15} fill={genMutation.isPending ? 0 : 1} />
      {genMutation.isPending
        ? t("experiments.cohort.generating")
        : value.generatedPool
          ? t("experiments.cohort.generateAgain")
          : t("experiments.cohort.generateCohort")}
    </button>
  );

  const synthActions = (
    <div className="flex flex-wrap items-center gap-2">
      {seedField}
      {synthButton}
    </div>
  );

  const progressAndResult = (
    <>
      {genMutation.isPending && progress ? (
        <div className="space-y-1">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-high/60">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${Math.round((progress.ratio || 0) * 100)}%` }}
            />
          </div>
          <div className="text-[11px] text-text-dim">{progress.label}</div>
        </div>
      ) : null}

      {value.generatedPool && !genMutation.isPending ? (
        <div className="space-y-2">
          <p className="inline-flex flex-wrap items-center gap-1.5 text-[11.5px] text-text-variant">
            <Sym name="check_circle" size={13} fill={1} className="text-secondary" />
            <span className="text-text-main">{value.generatedLabel ?? value.generatedPool}</span>
            {synthMode === "custom" ? (
              <span className="text-text-dim">
                ·{" "}
                {mix === "proportional"
                  ? t("experiments.cohort.mix.proportional.label")
                  : mix === "perCell"
                    ? t("experiments.cohort.mix.perCell.label")
                    : t("experiments.cohort.mix.random.label")}
              </span>
            ) : null}
          </p>
          {synthMode === "custom" && mix === "proportional" ? (
            <MixShareSummary
              filters={value.filters}
              overlays={value.overlays}
              marginals={value.marginals}
              catalog={catalog}
            />
          ) : null}
          <ArmCohortMap
            rows={detail.design.cells.map((cell, i) => {
              const level =
                Object.values(cell.factorLevels).join(" · ") ||
                cell.arm ||
                t("experiments.cohort.armN", { index: i + 1 });
              return {
                arm: level,
                group: t("experiments.cohort.shared"),
                n: value.generatedIds?.length ?? null,
                pool: value.generatedPool,
                reference: Boolean(cell.baseline),
              };
            })}
          />
        </div>
      ) : null}

      {genMutation.isError ? (
        <p className="rounded-md bg-danger/10 p-2 text-[11.5px] text-danger" role="alert">
          {errMessage(genMutation.error)}
        </p>
      ) : null}
    </>
  );

  const dimList =
    contractFields.length > 0
      ? contractFields.map((f) => dimName(f)).join(" × ")
      : null;

  return (
    <div className="space-y-2">
      <SegmentedChoice
        label={t("experiments.cohort.howToBuild")}
        icon="auto_awesome"
        value={synthMode}
        options={synthModes(t)}
        onChange={(next) => {
          if (next === synthMode) return;
          onChange({
            ...value,
            synthMode: next,
            generatedPool: undefined,
            generatedIds: undefined,
            generatedLabel: undefined,
            ...(next === "custom"
              ? {
                  fields: [],
                  filters: emptyPersonaDimensionFilters(),
                  overlays: [],
                  marginals: {},
                }
              : {}),
          });
        }}
      />

      {synthMode === "contract" ? (
        <div className="rounded-lg bg-surface-lowest/55 p-2.5">
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
            <div className="min-w-0">
              <p className="text-[12px] font-medium text-text-main">{t("experiments.cohort.planTitle")}</p>
              <p className="mt-0.5 text-[11px] text-text-dim">
                {t("experiments.cohort.planReuseAllArms")}
              </p>
            </div>
            <div className="shrink-0">{synthActions}</div>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
            {sizeEditable ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="text-text-dim">{t("experiments.cohort.stat.people")} </span>
                <input
                  type="number"
                  min={1}
                  value={effectiveContractN}
                  onChange={(e) =>
                    onChange({
                      ...value,
                      contractSize: Math.max(1, Number(e.target.value) || 1),
                      generatedPool: undefined,
                      generatedIds: undefined,
                      generatedLabel: undefined,
                    })
                  }
                  className={`w-16 rounded-md border border-outline/40 bg-field/60 px-1.5 py-0.5 text-[12px] font-semibold tabular-nums text-text-main ${FOCUS_RING}`}
                />
                {sizeOverridden ? (
                  <button
                    type="button"
                    onClick={() =>
                      onChange({
                        ...value,
                        contractSize: undefined,
                        generatedPool: undefined,
                        generatedIds: undefined,
                        generatedLabel: undefined,
                      })
                    }
                    className={`text-[11px] text-text-dim underline-offset-2 hover:text-text-variant hover:underline ${FOCUS_RING}`}
                    title={t("experiments.cohort.resetToDefault", { count: contractN })}
                  >
                    · {t("experiments.cohort.defaultN", { count: contractN })}
                  </button>
                ) : (
                  <span className="text-[11px] text-text-dim">· {t("experiments.cohort.taskDefault")}</span>
                )}
              </span>
            ) : (
              <span>
                <span className="text-text-dim">{t("experiments.cohort.stat.people")} </span>
                <span className="font-semibold tabular-nums text-text-main">{contractN}</span>
              </span>
            )}
            <span>
              <span className="text-text-dim">{t("experiments.cohort.stat.mix")} </span>
              <span className="text-text-variant">
                {fill === "perCell"
                  ? t("experiments.cohort.perGroup", { count: strategyPerCell })
                  : fill === "proportional"
                    ? t("experiments.cohort.mix.proportional.label")
                    : t("experiments.cohort.mix.random.label")}
              </span>
            </span>
            {dimList ? (
              <span className="min-w-0">
                <span className="text-text-dim">{t("experiments.cohort.stat.groups")} </span>
                <span className="text-text-variant">
                  {dimList}
                  {contractCombos > 1 ? (
                    <span className="text-text-dim"> · {contractCombos}</span>
                  ) : null}
                </span>
              </span>
            ) : null}
          </div>
          <CohortComposition
            filters={taskFilters}
            portions={strategyPortions}
            fields={contractFields}
            fill={fill}
            dimName={dimName}
            valueLabel={(dim, v) => dimLabels.valueLabel(dim, v)}
          />
          {showSchemaGaps ? (
            <div className="mt-2 space-y-1.5 rounded-md border border-primary/25 bg-primary/[0.06] px-2.5 py-2">
              <p className="text-[12px] font-medium text-text-main">
                {t("experiments.cohort.customAttrsTitle")}
              </p>
              <p className="text-[11px] leading-snug text-text-dim">
                {t("experiments.cohort.customAttrsHint")}
              </p>
              <GapChips gaps={schemaGaps} catalog={catalog} />
            </div>
          ) : null}
          {showContractWho ? (
            <div className="mt-2">
              <WhoSummary
                spec={value}
                applies
                whoLabel={t("experiments.cohort.extraAttrs")}
                catalog={catalog}
                onOpen={onOpenSpec}
                onClearFilters={() =>
                  onChange({ ...value, filters: emptyPersonaDimensionFilters() })
                }
                onClearOverlays={() => onChange({ ...value, overlays: [] })}
              />
            </div>
          ) : null}
          {(genMutation.isPending && progress) ||
          (value.generatedPool && !genMutation.isPending) ||
          genMutation.isError ? (
            <div className="mt-2 space-y-2 border-t border-outline/25 pt-2">
              {progressAndResult}
            </div>
          ) : null}
        </div>
      ) : (
        <>
          <div className="space-y-2 rounded-lg bg-surface-lowest/55 p-2.5 text-[12.5px]">
            <MixModePicker
              value={mix}
              onChange={(genMode) =>
                onChange({
                  ...value,
                  genMode,
                  generatedPool: undefined,
                  generatedIds: undefined,
                })
              }
            />
            {customFields.length === 0 ? (
              <p className="text-[11.5px] text-text-dim">
                {mix === "random"
                  ? t("experiments.cohort.hint.addWhoRandom")
                  : mix === "perCell"
                    ? t("experiments.cohort.hint.chooseDimsPerCell")
                    : t("experiments.cohort.hint.chooseDimsShare")}
              </p>
            ) : null}
            <div className="flex flex-wrap items-center gap-3">
              {mix === "perCell" ? (
                <div className="flex items-center gap-2">
                  <label className="text-text-dim">{t("experiments.cohort.peoplePerGroup")}</label>
                  <input
                    type="number"
                    min={1}
                    value={value.perCell || ""}
                    onChange={(e) =>
                      onChange({
                        ...value,
                        perCell: Math.max(1, Number(e.target.value) || 1),
                      })
                    }
                    className={`w-24 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                  />
                  {customCombos > 0 ? (
                    <span className="text-text-dim">
                      {t("experiments.cohort.arrowTotal", { count: customCombos * (value.perCell || 0) })}
                    </span>
                  ) : null}
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <label className="text-text-dim">{t("experiments.cohort.totalPeople")}</label>
                  <input
                    type="number"
                    min={mix === "proportional" ? customCombos || 1 : 1}
                    value={value.count || ""}
                    onChange={(e) =>
                      onChange({
                        ...value,
                        count: Math.max(1, Number(e.target.value) || 1),
                      })
                    }
                    className={`w-24 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                  />
                </div>
              )}
            </div>
          </div>

          <WhoSummary
            spec={value}
            applies
            whoLabel={t("experiments.cohort.whoGenerate")}
            catalog={catalog}
            onOpen={onOpenSpec}
            onClearFilters={() =>
              onChange({ ...value, filters: emptyPersonaDimensionFilters() })
            }
            onClearOverlays={() => onChange({ ...value, overlays: [] })}
          />

          <div className="flex flex-wrap items-center gap-2">{synthActions}</div>
          {progressAndResult}
        </>
      )}
    </div>
  );
}

function FieldLabel({ icon, text }: { icon: string; text: string }) {
  return (
    <label className="mb-1 flex items-center gap-1.5 text-[11.5px] font-medium text-text-dim">
      <Sym name={icon} size={13} />
      {text}
    </label>
  );
}

async function resolvePutArmSlices(args: {
  source: SutSource;
  pool: string;
  taskPath: string;
  dimension: string;
  values: string[];
  genMode: GenMixMode;
  perArm: number;
  count: number;
  seed: number;
  synthMode: SutSynthMode;
  eligibility: Record<string, string[]>;
  overlays: OverlayDimension[];
  strategyFields: string[];
  strategyAllocation: string;
  t: Translate;
  onArmProgress?: (event: PutContrastProgress) => void;
}): Promise<{ arms: PutArmCohort[]; generatedPool?: string; generatedLabel?: string }> {
  const t = args.t;
  const dimFilter = args.eligibility;
  const pool = args.pool;

  // Synthesize: one shared base cohort + a matched clone per tested value. Each
  // arm is DAG-validated on the backend; an arm that can't pass comes back with
  // an error while the rest still populate (paired, not split).
  if (args.source === "generate") {
    const overlays = args.overlays.length > 0 ? args.overlays : undefined;
    const contract = args.synthMode === "contract";
    const perArmN = args.genMode === "perCell" ? args.perArm : args.count;
    const res = await api.putContrastArms(
      {
        dimension: args.dimension,
        values: args.values,
        seed: args.seed,
        overlayDimensions: overlays,
        ...(contract
          ? { taskPath: args.taskPath }
          : {
              dimensionFilters: dimFilter,
              ...(perArmN > 0 ? { sampleSize: perArmN } : {}),
            }),
      },
      args.onArmProgress ? { onProgress: args.onArmProgress } : undefined,
    );
    const arms: PutArmCohort[] = res.arms.map((a) => ({
      label: a.value,
      dimensionValue: a.value,
      personaIds: a.personaIds ?? [],
      personaPool: a.pool ?? "",
      error: a.error,
    }));
    if (arms.every((a) => a.error)) {
      throw new Error(
        res.arms.find((a) => a.error)?.error ||
          t("experiments.cohort.error.noGroups"),
      );
    }
    return {
      arms,
      generatedLabel: t("experiments.cohort.put.baseMatched", {
        base: res.baseCount,
        count: arms.length,
      }),
    };
  }

  // Dataset draw: block attributes/values the dataset doesn't actually carry.
  await assertDatasetHasContrast(pool, args.dimension, args.values, t);

  if (args.genMode === "perCell") {
    const arms: PutArmCohort[] = [];
    for (const value of args.values) {
      const result = await api.samplePersonaPool({
        pool,
        taskPath: args.taskPath,
        sampleSize: args.perArm,
        seed: args.seed,
        dimensionFilters: { ...dimFilter, [args.dimension]: [value] },
      });
      if (result.personaIds.length === 0) {
        throw new Error(
          t("experiments.cohort.error.noPersonasMatched", {
            dim: humanizeToken(args.dimension),
            value,
          }),
        );
      }
      arms.push({
        label: value,
        dimensionValue: value,
        personaIds: result.personaIds,
        personaPool: result.pool ?? pool,
      });
    }
    return { arms };
  }

  const total = args.count;
  const batch = await api.samplePersonaPool({
    pool,
    taskPath: args.taskPath,
    seed: args.seed,
    dimensionFilters: dimFilter,
    // The contrast dimension is rarely a card dimension, so ask for it
    // explicitly — otherwise the returned cards can't be grouped by it.
    includeDimensions: [args.dimension],
    ...(args.genMode === "random"
      ? { sampleSize: total }
      : {
          fields: [args.dimension],
          allocation: "proportional",
          sampleSize: total,
        }),
  });
  const arms = partitionPutArms(batch, args.dimension, args.values, pool, t);
  const empty = arms.filter((a) => a.personaIds.length === 0);
  if (empty.length > 0) {
    throw new Error(
      t("experiments.cohort.error.noPersonasFor", {
        dim: humanizeToken(args.dimension),
        values: empty.map((a) => a.dimensionValue).join(", "),
      }),
    );
  }
  return { arms };
}

/**
 * Dataset mode only supports attributes/values the dataset actually carries.
 * Custom (unseen) ones must be built by Synthesize, so fail early with a clear
 * pointer rather than silently drawing an empty group.
 */
async function assertDatasetHasContrast(
  pool: string,
  dimension: string,
  values: string[],
  t: Translate,
): Promise<void> {
  if (!pool) return;
  let catalog: PersonaPoolCatalog;
  try {
    catalog = await api.getPersonaPoolCatalog(pool);
  } catch {
    return; // Catalog unavailable — let the sample call surface any issue.
  }
  const options = new Map<string, Set<string>>();
  const groups = catalog.dimensionCategories?.devProfile?.groups ?? [];
  for (const group of groups) {
    for (const dim of group.dimensions ?? []) {
      options.set(dim.id, new Set(dim.values ?? []));
    }
    for (const sub of group.subgroups ?? []) {
      for (const dim of sub.dimensions ?? []) {
        options.set(dim.id, new Set(dim.values ?? []));
      }
    }
  }
  for (const overlay of catalog.overlayDimensions ?? []) {
    options.set(overlay.id, new Set(overlay.values ?? []));
  }
  const dimName = humanizeToken(dimension);
  const have = options.get(dimension);
  if (!have) {
    throw new Error(t("experiments.cohort.error.notAnAttribute", { dim: dimName }));
  }
  const missing = values.filter((v) => !have.has(v));
  if (missing.length > 0) {
    throw new Error(
      t("experiments.cohort.error.datasetMissingValues", {
        dim: dimName,
        values: missing.join(", "),
        count: missing.length,
      }),
    );
  }
}

function partitionPutArms(
  result: PersonaPoolSampleResult,
  dim: string,
  values: string[],
  pool: string,
  t: Translate,
): PutArmCohort[] {
  const byVal = new Map<string, string[]>();
  for (const v of values) byVal.set(v, []);
  for (const p of result.personas ?? []) {
    const val = p.dimensions?.[dim];
    if (val && byVal.has(val)) byVal.get(val)!.push(p.personaId);
  }
  if ([...byVal.values()].every((ids) => ids.length === 0) && result.personaIds.length > 0) {
    throw new Error(
      t("experiments.cohort.error.noneCarried", {
        count: result.personaIds.length,
        dim: humanizeToken(dim),
      }),
    );
  }
  return values.map((v) => ({
    label: v,
    dimensionValue: v,
    personaIds: byVal.get(v) ?? [],
    personaPool: result.pool ?? pool,
  }));
}

/**
 * PUT contrast: one cohort slice per selected attribute value. Source is
 * dataset (draw) or synthesize; the task's putDimension is locked so generated
 * groups stay aligned with what the experiment measures.
 */
export function PutCohortPanel({
  detail,
  value,
  onChange,
}: {
  detail: TaskDetail;
  value: PutCohortSpec;
  onChange: (next: PutCohortSpec) => void;
}) {
  const { t, rich } = useI18n();
  const datasetsQuery = useQuery<PersonaDatasetListResponse>({
    queryKey: ["persona-datasets"],
    queryFn: api.listPersonaDatasets,
  });
  const [progress, setProgress] = useState<PersonaPoolGenerateProgress | null>(null);
  const [armStatus, setArmStatus] = useState<
    Record<string, { state: "running" | "done" | "error"; count?: number; error?: string }>
  >({});
  const [filterOpen, setFilterOpen] = useState(false);
  const set = (patch: Partial<PutCohortSpec>) => onChange({ ...value, ...patch, arms: null });

  const dimension = putDimensionId(detail);
  const dimLabel = humanizeToken(dimension);
  const dimValues = dimension ? (detail.cohortStrategy.dimensionFilters?.[dimension] ?? []) : [];
  const synthMode = value.synthMode ?? "contract";
  const extraFilters = value.filters ?? emptyPersonaDimensionFilters();
  const extraOverlays = value.overlays ?? [];
  const catalogPool =
    value.source === "generate" ? PERSONA_BENCH_POOL : value.pool || PERSONA_BENCH_POOL;
  const catalogQuery = useQuery<PersonaPoolCatalog>({
    queryKey: ["persona-pool-catalog", catalogPool],
    queryFn: () => api.getPersonaPoolCatalog(catalogPool),
    staleTime: 60_000,
  });
  const catalog = catalogQuery.data ?? null;
  const dimLabels = useDimensionLabels();
  const dimName = (id: string) =>
    catalogDimDisplayLabel(catalog, id, dimLabels, extraOverlays);

  const taskFilters = detail.cohortStrategy.dimensionFilters ?? {};
  const strategySampling = detail.cohortStrategy.sampling;
  const strategyFields =
    strategySampling?.fields && strategySampling.fields.length > 0
      ? strategySampling.fields
      : Object.keys(taskFilters);
  const strategyPerCell = strategySampling?.perCell ?? 1;
  const strategyAllocation = strategySampling?.allocation || "perCell";
  const strategyFill = fillModeFromStrategy(strategySampling);
  const strategyPortions =
    detail.cohortStrategy.portions ||
    detail.cohortStrategy.sampling?.portions ||
    null;
  const comboFilters = { ...taskFilters, [dimension]: value.values };
  const contractCombos = strategyFields.reduce(
    (acc, f) => acc * Math.max(1, (comboFilters[f] ?? []).length),
    1,
  );
  const contractN = Math.max(1, contractCombos * Math.max(1, strategyPerCell));
  // Optional operator override of the synthesized total; per-cell fill derives N
  // from groups × per-group so only share/random totals are editable here.
  const sizeEditable = strategyFill !== "perCell";
  const effectiveContractN = value.contractSize ?? contractN;
  const sizeOverridden =
    value.contractSize != null && value.contractSize !== contractN;
  const cohortDims = Object.fromEntries(
    Object.entries(taskFilters).filter(
      ([id, vals]) => id !== dimension && (vals?.length ?? 0) > 0,
    ),
  );
  const cohortFields = strategyFields.filter((f) => f !== dimension);

  const poolOptions = datasetsQuery.data?.datasets ?? [];
  const datasetSelectOptions = useMemo<CockpitSelectOption[]>(() => {
    const options: CockpitSelectOption[] = poolOptions.map((p) => ({
      value: p.pool,
      label: p.label,
      meta:
        typeof p.count === "number"
          ? t("experiments.cohort.personaCount", { count: p.count })
          : undefined,
    }));
    if (value.pool && !options.some((o) => o.value === value.pool)) {
      options.unshift({
        value: value.pool,
        label: poolSlug(value.pool),
        meta: t("experiments.cohort.taskDefault"),
      });
    }
    return options;
  }, [poolOptions, value.pool, t]);

  const mix = value.genMode ?? "perCell";
  const fillForDraw =
    value.source === "generate" && synthMode === "contract" ? strategyFill : mix;
  const nPerArm =
    value.source === "generate" && synthMode === "contract"
      ? strategyPerCell
      : value.perArm;
  const nTotal =
    value.source === "generate" && synthMode === "contract"
      ? effectiveContractN
      : value.count;

  const drawMutation = useMutation({
    mutationFn: async () => {
      setProgress(null);
      setArmStatus({});
      const onArmProgress =
        value.source === "generate"
          ? (e: PutContrastProgress) => {
              setProgress({
                type: "progress",
                stage: e.stage,
                ratio: e.ratio ?? 0,
                label: e.label ?? "",
              });
              if (e.stage === "arm" && e.value) {
                const state =
                  e.state === "done"
                    ? "done"
                    : e.state === "error"
                      ? "error"
                      : "running";
                setArmStatus((prev) => ({
                  ...prev,
                  [e.value as string]: { state, count: e.count, error: e.error },
                }));
              }
            }
          : undefined;
      return resolvePutArmSlices({
        source: value.source,
        pool: value.pool,
        taskPath: detail.task,
        dimension,
        values: value.values,
        genMode: fillForDraw,
        perArm: nPerArm,
        count: nTotal,
        seed: value.seed,
        synthMode,
        eligibility: putEligibilityFilters({
          dimension,
          values: value.values,
          synthMode,
          taskFilters,
          extraFilters,
          overlays: extraOverlays,
        }),
        overlays: value.source === "generate" ? extraOverlays : [],
        strategyFields,
        strategyAllocation,
        t,
        onArmProgress,
      });
    },
    onSuccess: (result) => {
      onChange({
        ...value,
        arms: result.arms,
        generatedPool: result.generatedPool,
        generatedLabel: result.generatedLabel,
      });
    },
  });

  const env = detail.design.cells.find((c) => c.baseline) ?? detail.design.cells[0];
  const factorLabel: Record<string, string> = {};
  const levelLabel: Record<string, Record<string, string>> = {};
  for (const f of detail.factors) {
    factorLabel[f.id] = f.label || f.id;
    levelLabel[f.id] = {};
    for (const lv of f.levels) levelLabel[f.id][lv.id] = lv.label || lv.id;
  }
  const mapRows = value.values.map((v, i) => {
    const slice = value.arms?.find((a) => a.dimensionValue === v);
    const live = armStatus[v];
    const vLabel = dimLabels.valueLabel(dimension, v);
    const n =
      slice?.personaIds.length ??
      (live?.state === "done" ? live.count ?? null : null);
    const error = slice?.error ?? (live?.state === "error" ? live.error ?? null : null);
    return {
      arm: vLabel,
      group: `${dimName(dimension) || dimLabel} = ${vLabel}`,
      n,
      pool:
        slice?.personaPool ??
        value.generatedPool ??
        (value.source === "dataset" ? value.pool : null),
      reference: i === 0,
      error,
      pending: !slice && live?.state === "running",
    };
  });

  const canDraw =
    Boolean(dimension) &&
    value.values.length >= 2 &&
    (value.source === "generate" && synthMode === "contract"
      ? true
      : mix === "perCell"
        ? value.perArm > 0
        : value.count >= value.values.length);

  const actionButton = (
    <button
      type="button"
      onClick={() => drawMutation.mutate()}
      disabled={!canDraw || drawMutation.isPending}
      className={`inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-semibold text-on-primary transition hover:bg-primary-dim disabled:opacity-50 ${FOCUS_RING}`}
    >
      <Sym
        name={value.source === "generate" ? "auto_awesome" : "download"}
        size={15}
        fill={drawMutation.isPending ? 0 : 1}
      />
      {drawMutation.isPending
        ? value.source === "generate"
          ? t("experiments.cohort.synthesizing")
          : t("experiments.cohort.drawing")
        : value.arms
          ? value.source === "generate"
            ? t("experiments.cohort.reSynthesize")
            : t("experiments.cohort.reDraw")
          : value.source === "generate"
            ? t("experiments.cohort.put.synthesizeTitle")
            : t("experiments.cohort.draw")}
    </button>
  );

  const seedField = (
    <div className="flex items-center gap-2">
      <label className="text-text-dim">{t("experiments.cohort.seed")}</label>
      <input
        type="number"
        value={value.seed}
        onChange={(e) => set({ seed: Number(e.target.value) || 0 })}
        className={`w-20 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
      />
    </div>
  );

  const mixSizeFields = (
    <>
      {mix === "perCell" ? (
        <div className="flex items-center gap-2">
          <label className="text-text-dim">{t("experiments.cohort.nPerArm")}</label>
          <input
            type="number"
            min={1}
            value={value.perArm || ""}
            onChange={(e) => set({ perArm: Math.max(1, Number(e.target.value) || 1) })}
            className={`w-24 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
          />
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <label className="text-text-dim">{t("experiments.cohort.n")}</label>
          <input
            type="number"
            min={value.values.length || 2}
            value={value.count || ""}
            onChange={(e) => set({ count: Math.max(1, Number(e.target.value) || 1) })}
            className={`w-24 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
          />
        </div>
      )}
      {seedField}
      {actionButton}
    </>
  );

  const progressAndMap = (
    <>
      {drawMutation.isPending && progress ? (
        <div className="space-y-1">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-high/60">
            <div
              className="h-full rounded-full bg-secondary transition-all"
              style={{ width: `${Math.round((progress.ratio || 0) * 100)}%` }}
            />
          </div>
          <div className="text-[11px] text-text-dim">{progress.label}</div>
        </div>
      ) : null}

      {value.values.length >= 2 ? (
        <ArmCohortMap
          rows={mapRows}
          emptyLabel={
            value.source === "generate"
              ? t("experiments.cohort.notSynthesizedYet")
              : t("experiments.cohort.notDrawnYet")
          }
        />
      ) : (
        <p className="text-[12px] text-text-dim">{t("experiments.cohort.select2Values")}</p>
      )}

      {drawMutation.isError ? (
        <p className="rounded-md bg-danger/10 p-2 text-[11.5px] text-danger" role="alert">
          {errMessage(drawMutation.error)}
        </p>
      ) : null}
    </>
  );

  const whoSummary = (
    <WhoSummary
      spec={{
        source: "generate",
        synthMode,
        genMode: mix,
        filters: extraFilters,
        overlays: extraOverlays,
        marginals: value.marginals ?? {},
      }}
      applies
      whoLabel={t("experiments.cohort.whoEligible")}
      emptyHint={t("experiments.cohort.put.whoEmptyHint")}
      showShare={false}
      catalog={catalog}
      onOpen={() => setFilterOpen(true)}
      onClearFilters={() => set({ filters: emptyPersonaDimensionFilters() })}
      onClearOverlays={() => set({ overlays: [] })}
    />
  );

  return (
    <div className="space-y-3">
      {env && Object.keys(env.factorLevels).length > 0 ? (
        <div className="rounded-lg border border-outline/30 bg-surface/40 p-2.5 text-[12px]">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-text-main">
            <Sym name="lock" size={13} className="text-text-dim" /> {t("experiments.cohort.environment")}
          </div>
          <div className="flex flex-wrap gap-1.5 text-text-variant">
            {Object.entries(env.factorLevels).map(([f, l]) => (
              <span key={f} className="rounded bg-surface-high/60 px-1.5 py-0.5">
                {factorLabel[f] ?? humanizeToken(f)}: {levelLabel[f]?.[l] ?? l}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div>
        <FieldLabel icon="dataset" text={t("experiments.cohort.source.label")} />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <SourceCard
            active={value.source === "dataset"}
            onClick={() => set({ source: "dataset" })}
            icon="dataset"
            title={t("experiments.cohort.dataset.label")}
            desc={t("experiments.cohort.put.datasetDesc")}
          />
          <SourceCard
            active={value.source === "generate"}
            onClick={() => set({ source: "generate", synthMode: "contract" })}
            icon="auto_awesome"
            title={t("experiments.cohort.put.synthesizeTitle")}
            desc={t("experiments.cohort.put.synthesizeDesc")}
          />
        </div>
      </div>

      {value.source === "dataset" ? (
        <div className="w-full max-w-3xl">
          <CockpitSelect
            label={t("experiments.cohort.dataset.label")}
            value={value.pool}
            options={datasetSelectOptions}
            onChange={(pool) => set({ pool })}
            inlineLabel
            wideMenu
            wrapOptions
            showSelectedMeta={false}
          />
        </div>
      ) : null}

      {dimValues.length === 0 ? (
        <p className="rounded-md bg-warn/10 p-2.5 text-[12px] text-text-variant">
          <Sym name="warning" size={13} className="mr-1 inline text-warn" />
          {t("experiments.cohort.noValuesForDim", {
            dim: dimLabel || t("experiments.cohort.contrast"),
          })}
        </p>
      ) : (
        <>
          <div>
            <FieldLabel
              icon="science"
              text={`${t("experiments.cohort.compareBy")} · ${
                dimName(dimension) || dimLabel || t("experiments.cohort.attribute")
              }`}
            />
            <p className="mb-1.5 text-[11.5px] leading-snug text-text-dim">
              {rich("experiments.cohort.baselineHint", {
                flag: () => (
                  <Sym name="flag" size={11} className="inline align-[-1px]" />
                ),
              })}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {dimValues.map((v) => {
                const idx = value.values.indexOf(v);
                const active = idx >= 0;
                const vLabel = dimLabels.valueLabel(dimension, v);
                return (
                  <button
                    key={v}
                    type="button"
                    title={
                      active
                        ? idx === 0
                          ? t("experiments.cohort.value.baseline", { label: vLabel })
                          : t("experiments.cohort.value.group", { label: vLabel, index: idx + 1 })
                        : t("experiments.cohort.value.add", { label: vLabel })
                    }
                    onClick={() =>
                      set({
                        values: active
                          ? value.values.filter((x) => x !== v)
                          : [...value.values, v],
                      })
                    }
                    className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[12px] transition ${FOCUS_RING} ${
                      active ? CHOICE_ON : CHOICE_IDLE
                    }`}
                  >
                    {active ? <Sym name={idx === 0 ? "flag" : "check"} size={12} /> : null}
                    {vLabel}
                  </button>
                );
              })}
            </div>
          </div>

          {value.source === "generate" ? (
            <>
              <SegmentedChoice
                label={t("experiments.cohort.howToBuild")}
                icon="auto_awesome"
                value={synthMode}
                options={synthModes(t)}
                onChange={(next) => {
                  if (next === synthMode) return;
                  set({
                    synthMode: next,
                    ...(next === "custom"
                      ? {
                          filters: emptyPersonaDimensionFilters(),
                          overlays: [],
                          marginals: {},
                        }
                      : {}),
                  });
                }}
              />

              {synthMode === "contract" ? (
                <div className="rounded-lg bg-surface-lowest/55 p-2.5">
                  <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
                    <div className="min-w-0">
                      <p className="text-[12px] font-medium text-text-main">
                        {t("experiments.cohort.planTitle")}
                      </p>
                      <p className="mt-0.5 text-[11px] text-text-dim">
                        {t("experiments.cohort.planSlicePerValue")}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {seedField}
                      {actionButton}
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
                    {sizeEditable ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span className="text-text-dim">{t("experiments.cohort.stat.people")} </span>
                        <input
                          type="number"
                          min={1}
                          value={effectiveContractN}
                          onChange={(e) =>
                            set({
                              contractSize: Math.max(1, Number(e.target.value) || 1),
                              generatedPool: undefined,
                              generatedLabel: undefined,
                            })
                          }
                          className={`w-16 rounded-md border border-outline/40 bg-field/60 px-1.5 py-0.5 text-[12px] font-semibold tabular-nums text-text-main ${FOCUS_RING}`}
                        />
                        {sizeOverridden ? (
                          <button
                            type="button"
                            onClick={() =>
                              set({
                                contractSize: undefined,
                                generatedPool: undefined,
                                generatedLabel: undefined,
                              })
                            }
                            className={`text-[11px] text-text-dim underline-offset-2 hover:text-text-variant hover:underline ${FOCUS_RING}`}
                            title={t("experiments.cohort.resetToDefault", { count: contractN })}
                          >
                            · {t("experiments.cohort.defaultN", { count: contractN })}
                          </button>
                        ) : (
                          <span className="text-[11px] text-text-dim">· {t("experiments.cohort.taskDefault")}</span>
                        )}
                      </span>
                    ) : (
                      <span>
                        <span className="text-text-dim">{t("experiments.cohort.stat.people")} </span>
                        <span className="font-semibold tabular-nums text-text-main">
                          {contractN}
                        </span>
                      </span>
                    )}
                    <span>
                      <span className="text-text-dim">{t("experiments.cohort.stat.mix")} </span>
                      <span className="text-text-variant">
                        {strategyFill === "perCell"
                          ? t("experiments.cohort.perGroup", { count: strategyPerCell })
                          : strategyFill === "proportional"
                            ? t("experiments.cohort.mix.proportional.label")
                            : t("experiments.cohort.mix.random.label")}
                      </span>
                    </span>
                    {strategyFields.length > 0 ? (
                      <span className="min-w-0">
                        <span className="text-text-dim">{t("experiments.cohort.stat.groups")} </span>
                        <span className="text-text-variant">
                          {strategyFields.map((f) => dimName(f)).join(" × ")}
                          {contractCombos > 1 ? (
                            <span className="text-text-dim"> · {contractCombos}</span>
                          ) : null}
                        </span>
                      </span>
                    ) : null}
                  </div>
                  <CohortComposition
                    filters={cohortDims}
                    portions={strategyPortions}
                    fields={cohortFields}
                    fill={strategyFill}
                    dimName={dimName}
                    valueLabel={(dim, v) => dimLabels.valueLabel(dim, v)}
                  />
                </div>
              ) : (
                <>
                  <div className="space-y-2 rounded-lg bg-surface-lowest/55 p-2.5 text-[12.5px]">
                    <MixModePicker value={mix} onChange={(genMode) => set({ genMode })} />
                    <div className="flex flex-wrap items-center gap-3">
                      {mix === "perCell" ? (
                        <div className="flex items-center gap-2">
                          <label className="text-text-dim">{t("experiments.cohort.nPerArm")}</label>
                          <input
                            type="number"
                            min={1}
                            value={value.perArm || ""}
                            onChange={(e) =>
                              set({ perArm: Math.max(1, Number(e.target.value) || 1) })
                            }
                            className={`w-24 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                          />
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <label className="text-text-dim">{t("experiments.cohort.n")}</label>
                          <input
                            type="number"
                            min={value.values.length || 2}
                            value={value.count || ""}
                            onChange={(e) =>
                              set({ count: Math.max(1, Number(e.target.value) || 1) })
                            }
                            className={`w-24 rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                  {whoSummary}
                  <div className="flex flex-wrap items-center gap-2">
                    {seedField}
                    {actionButton}
                  </div>
                </>
              )}
            </>
          ) : (
            <>
              <MixModePicker value={mix} onChange={(genMode) => set({ genMode })} />
              <div className="flex flex-wrap items-center gap-4 text-[12px]">{mixSizeFields}</div>
            </>
          )}

          {progressAndMap}
        </>
      )}

      <PersonaFilterModal
        open={filterOpen}
        catalog={catalog}
        filters={extraFilters}
        stratifyMode={false}
        showMarginals={false}
        allowOverlayEdit
        showSelectedPane={false}
        overlayDimensions={extraOverlays}
        onClose={() => setFilterOpen(false)}
        onConfirm={(next, nextMarginals, nextOverlay) => {
          const dimensionFilters = { ...next.dimensionFilters };
          if (dimension) delete dimensionFilters[dimension];
          set({
            filters: { ...next, dimensionFilters },
            ...(nextMarginals !== undefined ? { marginals: nextMarginals } : {}),
            ...(nextOverlay !== undefined ? { overlays: nextOverlay } : {}),
          });
        }}
      />
    </div>
  );
}
