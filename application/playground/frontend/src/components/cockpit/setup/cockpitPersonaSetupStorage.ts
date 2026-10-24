import type { HarborCockpitTaskKind } from "@/lib/harborCockpitMappers";
import type { TaskPersonaStrategy } from "@/lib/types";
import { PERSONA_BENCH_POOL, PERSONA_CARD_PREVIEW_LIMIT, PERSONA_UI_ID_LIST_MAX } from "@/lib/types";

import { readCockpitBatch } from "./cockpitBatchStorage";
import {
  emptyPersonaDimensionFilters,
  readStrategySampling,
  type PersonaDimensionFilters,
  type PersonaSamplingMode,
  type StratifiedAllocation,
} from "./personaSamplingTypes";

/** Legacy pool slug renamed to matraix-persona-dev-sample (directory removed). */
const LEGACY_BENCH_DEV_SAMPLE = "persona/datasets/bench-dev-sample";

/**
 * One-time Task-default fill pools (`generated-persona-dev-strategy-*`).
 * Owned by Task default ON + Pull/Synthesize — not a durable Dataset choice.
 */
export function isTaskStrategyFillPool(pool: string | null | undefined): boolean {
  return /(?:^|\/)generated-persona-dev-strategy-/.test((pool ?? "").trim());
}

/** Drop legacy / ephemeral pools that must not sticky-restore as Dataset. */
export function sanitizePersonaPool(pool: string | null | undefined): string {
  const text = (pool ?? "").trim();
  if (!text) return PERSONA_BENCH_POOL;
  // Allow launch caches next to their source dataset; drop leftover synthetic pools.
  if (/persona\/datasets\/[^/]+\/cohorts\/cohort-/.test(text)) {
    return text;
  }
  if (text.includes("/_generated/")) {
    return PERSONA_BENCH_POOL;
  }
  // Old cockpit / task setups still point at the removed bench-dev-sample path.
  if (text === LEGACY_BENCH_DEV_SAMPLE || text.endsWith("/bench-dev-sample")) {
    return PERSONA_BENCH_POOL;
  }
  return text;
}

/** Operator-picked Dataset + people (not a task-fill generate pool). */
export function hasDurableOperatorCohort(input: {
  personaPool?: string | null;
  selectedPersonaIds?: string[];
  selectedCount?: number;
  useEntirePool?: boolean;
}): boolean {
  if (isTaskStrategyFillPool(input.personaPool)) return false;
  if (!(input.personaPool ?? "").trim()) return false;
  return (
    input.useEntirePool === true ||
    (input.selectedPersonaIds?.length ?? 0) > 0 ||
    (input.selectedCount ?? 0) > 0
  );
}

/** Sampling UI that matches an explicit launch cohort (not strategy stratified-N). */
export function samplingModeForOperatorCohort(input: {
  selectedPersonaIds: string[];
  selectedCount?: number;
  useEntirePool?: boolean;
}): PersonaSamplingMode {
  if (input.useEntirePool) return "all";
  const size = Math.max(input.selectedCount ?? 0, input.selectedPersonaIds.length);
  if (size <= 1) return "single";
  return "random";
}

export interface CockpitPersonaSetupRecord {
  selectedPersonaIds: string[];
  /** Full cohort size (may exceed selectedPersonaIds when launching by pool ref). */
  selectedCount: number;
  /** When true, launch uses the whole personaPool without echoing IDs. */
  useEntirePool: boolean;
  samplingMode: PersonaSamplingMode;
  groupFilters: PersonaDimensionFilters;
  fields: string[];
  /** Stratified allocation: perCell | proportional | equalTotal. */
  stratifiedAllocation: StratifiedAllocation;
  sampleSize: number;
  /**
   * Personas per stratify combination (stratified + perCell).
   * `null` when allocation is proportional / equalTotal — use `sampleSize` instead.
   */
  perCell: number | null;
  parallelTrials: number;
  personaModel: string;
  /** Pool used for the current cohort (never restore leftover synthetic paths). */
  personaPool: string;
  /** When true, sampling follows the task's persona_strategy.json and custom filters stay locked. */
  useTaskDefaultStrategy: boolean;
  /**
   * Set only when the operator explicitly turns Task default strategy off.
   * Distinguishes intentional opt-out from the pre-hydrate false that used to
   * poison localStorage before persona_strategy.json loaded.
   */
  taskDefaultStrategyDismissed?: boolean;
}

type CockpitPersonaSetupStore = {
  byTaskPath?: Record<string, CockpitPersonaSetupRecord>;
  /** Legacy kind-keyed entries (pre task-path storage). */
  byKind?: Partial<Record<HarborCockpitTaskKind, CockpitPersonaSetupRecord>>;
};

const STORAGE_KEY = "playground.cockpitPersonaSetupByTaskPath";
const LEGACY_STORAGE_KEY = "playground.cockpitPersonaSetupByTask";
const MODEL_MIGRATION_KEY = "playground.cockpitModelMigrated_v2";
const OLD_DEFAULT_MODEL = "anthropic/claude-sonnet-4-6";
const NEW_DEFAULT_MODEL = "anthropic/claude-haiku-4-5";

/**
 * One-shot migration: replace the old os-app default (Sonnet 4.6) with
 * the new default (Haiku 4.5) in every cached persona setup record.
 */
function migrateDefaultModelOnce(): void {
  if (typeof window === "undefined") return;
  if (window.localStorage.getItem(MODEL_MIGRATION_KEY)) return;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const store = JSON.parse(raw) as CockpitPersonaSetupStore;
      let changed = false;
      if (store.byTaskPath) {
        for (const record of Object.values(store.byTaskPath)) {
          if (record.personaModel === OLD_DEFAULT_MODEL) {
            record.personaModel = NEW_DEFAULT_MODEL;
            changed = true;
          }
        }
      }
      if (store.byKind) {
        for (const record of Object.values(store.byKind)) {
          if (record && record.personaModel === OLD_DEFAULT_MODEL) {
            record.personaModel = NEW_DEFAULT_MODEL;
            changed = true;
          }
        }
      }
      if (changed) {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
      }
    }
  } catch {
    /* ignore */
  }
  window.localStorage.setItem(MODEL_MIGRATION_KEY, "1");
}

function readStore(): CockpitPersonaSetupStore {
  if (typeof window === "undefined") return {};
  migrateDefaultModelOnce();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as CockpitPersonaSetupStore;
      if (parsed && typeof parsed === "object") return parsed;
    }
  } catch {
    /* ignore */
  }
  // Migrate legacy kind-keyed blob once.
  try {
    const legacyRaw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!legacyRaw) return {};
    const legacy = JSON.parse(legacyRaw) as Partial<
      Record<HarborCockpitTaskKind, CockpitPersonaSetupRecord>
    >;
    if (!legacy || typeof legacy !== "object") return {};
    return { byKind: legacy };
  } catch {
    return {};
  }
}

function writeStore(store: CockpitPersonaSetupStore): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}

function normalizeRecord(
  record: Partial<CockpitPersonaSetupRecord> | null | undefined,
  fallbackPersonaModel: string,
): CockpitPersonaSetupRecord | null {
  if (!record) return null;
  const selectedPersonaIds = Array.isArray(record.selectedPersonaIds)
    ? record.selectedPersonaIds
        .filter((id): id is string => typeof id === "string")
        .slice(0, PERSONA_UI_ID_LIST_MAX)
    : [];
  const selectedCount =
    typeof record.selectedCount === "number" && record.selectedCount > 0
      ? Math.round(record.selectedCount)
      : selectedPersonaIds.length;
  const useEntirePool =
    record.useEntirePool === true || selectedCount > PERSONA_UI_ID_LIST_MAX;
  return {
    selectedPersonaIds: useEntirePool
      ? selectedPersonaIds.slice(0, PERSONA_CARD_PREVIEW_LIMIT)
      : selectedPersonaIds,
    selectedCount,
    useEntirePool,
    samplingMode:
      record.samplingMode === "random" ||
      record.samplingMode === "stratified" ||
      record.samplingMode === "all"
        ? record.samplingMode
        : "single",
    groupFilters: record.groupFilters ?? emptyPersonaDimensionFilters(),
    fields: Array.isArray(record.fields)
      ? record.fields.filter((field): field is string => typeof field === "string")
      : [],
    stratifiedAllocation:
      record.stratifiedAllocation === "proportional" ||
      record.stratifiedAllocation === "equalTotal" ||
      record.stratifiedAllocation === "perCell"
        ? record.stratifiedAllocation
        : record.perCell === null
          ? "equalTotal"
          : "perCell",
    sampleSize: typeof record.sampleSize === "number" && record.sampleSize > 0 ? record.sampleSize : 4,
    perCell:
      record.perCell === null
        ? null
        : typeof record.perCell === "number" && record.perCell >= 1
          ? Math.round(record.perCell)
          : 1,
    parallelTrials:
      typeof record.parallelTrials === "number" && record.parallelTrials > 0 ? record.parallelTrials : 2,
    personaModel:
      typeof record.personaModel === "string" && record.personaModel && record.personaModel !== OLD_DEFAULT_MODEL
        ? record.personaModel
        : fallbackPersonaModel,
    personaPool: sanitizePersonaPool(
      typeof record.personaPool === "string" ? record.personaPool : PERSONA_BENCH_POOL,
    ),
    // Legacy entries omit this flag — prefer task default until the user turns it off.
    useTaskDefaultStrategy:
      typeof record.useTaskDefaultStrategy === "boolean" ? record.useTaskDefaultStrategy : true,
    taskDefaultStrategyDismissed: record.taskDefaultStrategyDismissed === true,
  };
}

export function defaultPersonaSetup(fallbackPersonaModel: string): CockpitPersonaSetupRecord {
  return {
    selectedPersonaIds: [],
    selectedCount: 0,
    useEntirePool: false,
    samplingMode: "single",
    groupFilters: emptyPersonaDimensionFilters(),
    // Stratify axes are operator-chosen — never seed Age/Region by default.
    fields: [],
    stratifiedAllocation: "perCell",
    sampleSize: 4,
    perCell: 1,
    parallelTrials: 2,
    personaModel: fallbackPersonaModel,
    personaPool: PERSONA_BENCH_POOL,
    useTaskDefaultStrategy: false,
  };
}

/**
 * Custom mode (Task default off) must not keep a task-fill cohort as Dataset.
 * Falls back to the previous non-fill dataset when one is known.
 */
export function scrubTaskStrategyFillForCustomMode(
  record: CockpitPersonaSetupRecord,
  fallbackPersonaModel: string,
  durablePool?: string | null,
): CockpitPersonaSetupRecord {
  if (!isTaskStrategyFillPool(record.personaPool)) return record;
  const defaults = defaultPersonaSetup(fallbackPersonaModel);
  const fallbackPool =
    durablePool && !isTaskStrategyFillPool(durablePool)
      ? sanitizePersonaPool(durablePool)
      : PERSONA_BENCH_POOL;
  return {
    ...defaults,
    personaPool: fallbackPool,
    personaModel: record.personaModel || defaults.personaModel,
    parallelTrials: record.parallelTrials || defaults.parallelTrials,
    useTaskDefaultStrategy: false,
    taskDefaultStrategyDismissed: true,
  };
}

/** Keep Dataset + selected ids as one selection and dismiss Task default. */
export function keepOperatorCohort(
  base: CockpitPersonaSetupRecord,
  cohort: {
    personaPool: string;
    selectedPersonaIds: string[];
    selectedCount: number;
    useEntirePool: boolean;
  },
): CockpitPersonaSetupRecord {
  const selectedPersonaIds = cohort.selectedPersonaIds;
  const selectedCount = cohort.selectedCount || selectedPersonaIds.length;
  return {
    ...base,
    personaPool: sanitizePersonaPool(cohort.personaPool),
    selectedPersonaIds,
    selectedCount,
    useEntirePool: cohort.useEntirePool,
    samplingMode: samplingModeForOperatorCohort({
      selectedPersonaIds,
      selectedCount,
      useEntirePool: cohort.useEntirePool,
    }),
    useTaskDefaultStrategy: false,
    taskDefaultStrategyDismissed: true,
  };
}

export type TaskHydrateIncomingCohort = {
  personaPool: string;
  selectedPersonaIds: string[];
  selectedCount: number;
  useEntirePool: boolean;
};

/**
 * Resolve cockpit persona state when a task path hydrates.
 *
 * Invariant: never launch pool A with ids from pool B. An operator pick
 * (Dataset + people) restores together and turns Task default off so the
 * rail matches POST. Task-fill pools stay ephemeral.
 */
export function resolveTaskHydrateSetup(input: {
  strategy: TaskPersonaStrategy | null | undefined;
  stored: CockpitPersonaSetupRecord;
  hasTaskSpecificStore: boolean;
  incoming: TaskHydrateIncomingCohort;
  fallbackPersonaModel: string;
}): CockpitPersonaSetupRecord {
  const { strategy, stored, hasTaskSpecificStore, incoming, fallbackPersonaModel } = input;
  const dismissed = stored.taskDefaultStrategyDismissed === true;
  const modelBase: CockpitPersonaSetupRecord = {
    ...defaultPersonaSetup(fallbackPersonaModel),
    personaModel: stored.personaModel || fallbackPersonaModel,
    parallelTrials: stored.parallelTrials,
  };

  // First visit of this task: honor people already on screen (or kind-level draft).
  if (!hasTaskSpecificStore && hasDurableOperatorCohort(incoming)) {
    return keepOperatorCohort(modelBase, incoming);
  }

  if (hasTaskSpecificStore && (dismissed || !strategy)) {
    return scrubTaskStrategyFillForCustomMode(
      {
        ...stored,
        useTaskDefaultStrategy: Boolean(strategy) && stored.useTaskDefaultStrategy,
        taskDefaultStrategyDismissed: dismissed,
      },
      fallbackPersonaModel,
    );
  }

  // This task's own fill pool is owned by Task default ON.
  if (hasTaskSpecificStore && isTaskStrategyFillPool(stored.personaPool)) {
    const applied = setupFromPersonaStrategy(strategy, fallbackPersonaModel, modelBase);
    applied.personaPool = sanitizePersonaPool(stored.personaPool);
    applied.selectedPersonaIds = stored.selectedPersonaIds;
    applied.selectedCount = stored.selectedCount || stored.selectedPersonaIds.length;
    applied.useEntirePool = stored.useEntirePool;
    return applied;
  }

  // Returning with an explicit Dataset pick: restore atomically, don't show
  // strategy stratified-N while launch would send those ids.
  if (hasTaskSpecificStore && hasDurableOperatorCohort(stored)) {
    return keepOperatorCohort(modelBase, stored);
  }

  // Task owns the cohort — do not paste leftover ids from a previous screen.
  return setupFromPersonaStrategy(strategy, fallbackPersonaModel, modelBase);
}

export function setupFromPersonaStrategy(
  strategy: TaskPersonaStrategy | null | undefined,
  fallbackPersonaModel: string,
  base?: CockpitPersonaSetupRecord,
): CockpitPersonaSetupRecord {
  const next = base ? { ...base } : defaultPersonaSetup(fallbackPersonaModel);
  if (!strategy) return next;

  const sampling = readStrategySampling(strategy);
  next.samplingMode = sampling.mode;

  next.groupFilters = {
    sources: Array.isArray(strategy.sources)
      ? strategy.sources.filter(
          (value): value is string => typeof value === "string" && Boolean(value.trim()),
        )
      : [],
    dimensionFilters:
      strategy.dimensionFilters && typeof strategy.dimensionFilters === "object"
        ? Object.fromEntries(
            Object.entries(strategy.dimensionFilters)
              .map(([key, values]) => [
                key,
                Array.isArray(values)
                  ? values.filter(
                      (value): value is string =>
                        typeof value === "string" && Boolean(value.trim()),
                    )
                  : [],
              ])
              .filter(([, values]) => (values as string[]).length > 0),
          )
        : {},
  };

  if (sampling.fields.length > 0) {
    next.fields = sampling.fields;
  }

  next.stratifiedAllocation = sampling.allocation;
  if (sampling.allocation === "perCell") {
    next.perCell = Math.min(
      50,
      Math.max(1, Math.round(sampling.perCell ?? 1)),
    );
  } else {
    next.perCell = null;
    if (sampling.sampleSize != null) {
      next.sampleSize = Math.min(500, Math.max(2, Math.round(sampling.sampleSize)));
    }
  }

  if (typeof strategy.pool === "string" && strategy.pool.trim()) {
    next.personaPool = sanitizePersonaPool(strategy.pool);
  }

  // Fresh strategy apply clears prior preview selection and locks custom filters.
  next.selectedPersonaIds = [];
  next.selectedCount = 0;
  next.useEntirePool = false;
  next.useTaskDefaultStrategy = true;
  next.taskDefaultStrategyDismissed = false;
  return next;
}

export function hasStoredPersonaSetup(taskPath: string | null | undefined): boolean {
  const path = taskPath?.trim() ?? "";
  if (!path) return false;
  const store = readStore();
  return Boolean(store.byTaskPath?.[path]);
}

export function readCockpitPersonaSetup(
  taskKind: HarborCockpitTaskKind,
  fallbackPersonaModel: string,
  taskPath?: string | null,
): CockpitPersonaSetupRecord {
  const store = readStore();
  const path = taskPath?.trim() ?? "";
  if (path) {
    const byPath = normalizeRecord(store.byTaskPath?.[path], fallbackPersonaModel);
    if (byPath) return byPath;
  }

  const byKind = normalizeRecord(store.byKind?.[taskKind], fallbackPersonaModel);
  if (byKind) return byKind;

  // Legacy key without wrapper.
  if (typeof window !== "undefined") {
    try {
      const legacyRaw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
      if (legacyRaw) {
        const legacy = JSON.parse(legacyRaw) as Partial<
          Record<HarborCockpitTaskKind, CockpitPersonaSetupRecord>
        >;
        const fromLegacy = normalizeRecord(legacy?.[taskKind], fallbackPersonaModel);
        if (fromLegacy) return fromLegacy;
      }
    } catch {
      /* ignore */
    }
  }

  const batch = readCockpitBatch(taskKind);
  if (batch?.personaIds.length) {
    return {
      ...defaultPersonaSetup(fallbackPersonaModel),
      selectedPersonaIds: batch.personaIds,
      selectedCount: batch.selectedCount || batch.personaIds.length,
      personaPool: sanitizePersonaPool(batch.personaPool || PERSONA_BENCH_POOL),
    };
  }

  return defaultPersonaSetup(fallbackPersonaModel);
}

export function writeCockpitPersonaSetup(
  taskKind: HarborCockpitTaskKind,
  record: CockpitPersonaSetupRecord,
  taskPath?: string | null,
): void {
  const store = readStore();
  const path = taskPath?.trim() ?? "";
  if (path) {
    store.byTaskPath = { ...(store.byTaskPath ?? {}), [path]: record };
  }
  // Last operator draft for this kind. New task paths fall back to byKind;
  // never sticky-restore a task-fill pool as Dataset.
  store.byKind = {
    ...(store.byKind ?? {}),
    [taskKind]: scrubTaskStrategyFillForCustomMode(record, record.personaModel),
  };
  writeStore(store);
}
