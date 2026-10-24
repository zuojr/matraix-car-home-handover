/** Persona sampling state shared by the cockpit left rail. */

import type {
  OverlayDimension,
  PersonaPoolCatalog,
  PersonaPoolDimensionGroup,
  TaskPersonaStrategy,
} from "@/lib/types";

export type PersonaSamplingMode = "single" | "random" | "stratified" | "all";

export type StratifiedAllocation = "perCell" | "proportional" | "equalTotal";

export interface PersonaDimensionFilters {
  sources: string[];
  /** dimension id → selected values (multi-select per dimension). */
  dimensionFilters: Record<string, string[]>;
}

export function emptyPersonaDimensionFilters(): PersonaDimensionFilters {
  return { sources: [], dimensionFilters: {} };
}

export function activeFilterCount(filters: PersonaDimensionFilters): number {
  const dimCount = Object.values(filters.dimensionFilters).filter((values) => values.length > 0).length;
  return filters.sources.length + dimCount;
}

/** Distinct filter dimensions vs selected attribute values (chips). */
export function filterSelectionCounts(filters: PersonaDimensionFilters): {
  dimensions: number;
  attributes: number;
} {
  const dimValues = Object.values(filters.dimensionFilters).filter((values) => values.length > 0);
  const dimAttributes = dimValues.reduce((sum, values) => sum + values.length, 0);
  const sourceCount = filters.sources.length;
  return {
    dimensions: dimValues.length + (sourceCount > 0 ? 1 : 0),
    attributes: dimAttributes + sourceCount,
  };
}

/** Set one value's share (0–100); remaining values keep their relative mix. */
export function setMarginalPercent(
  prev: Record<string, Record<string, number>>,
  dim: string,
  values: string[],
  changed: string,
  percent: number,
): Record<string, Record<string, number>> {
  const clamped = Math.max(0, Math.min(100, percent));
  const current = prev[dim] ?? {};
  const next: Record<string, number> = {};
  const others = values.filter((value) => value !== changed);
  if (others.length === 0) {
    next[changed] = 100;
    return { ...prev, [dim]: next };
  }
  const otherWeight = others.reduce((sum, value) => {
    const weight = current[value];
    return sum + (typeof weight === "number" && weight > 0 ? weight : 0);
  }, 0);
  const rest = 100 - clamped;
  next[changed] = clamped;
  if (otherWeight <= 0) {
    const each = rest / others.length;
    for (const value of others) next[value] = each;
  } else {
    for (const value of others) {
      const weight = current[value];
      const share = typeof weight === "number" && weight > 0 ? weight : 0;
      next[value] = rest * (share / otherWeight);
    }
  }
  return { ...prev, [dim]: next };
}

export function filterAxisIds(filters: PersonaDimensionFilters): string[] {
  return Object.entries(filters.dimensionFilters)
    .filter(([, values]) => values.length > 0)
    .map(([key]) => key);
}

export const STUDY_OVERLAY_GROUP_ID = "study-overlay";

export function overlayCatalogGroup(
  overlay: OverlayDimension[],
  label: string,
): PersonaPoolDimensionGroup {
  return {
    id: STUDY_OVERLAY_GROUP_ID,
    label,
    dimensionIds: overlay.map((dim) => dim.id),
    dimensions: overlay.map((dim) => ({
      id: dim.id,
      label: dim.label,
      values: dim.values,
    })),
  };
}

export function collectCatalogDimIds(
  catalog: PersonaPoolCatalog | null | undefined,
): Set<string> {
  const ids = new Set<string>();
  for (const group of catalog?.dimensionCategories?.devProfile?.groups ?? []) {
    if (group.id === STUDY_OVERLAY_GROUP_ID) continue;
    for (const dim of group.dimensions ?? []) ids.add(dim.id);
    for (const sub of group.subgroups ?? []) {
      for (const dim of sub.dimensions ?? []) ids.add(dim.id);
    }
  }
  return ids;
}

/** Machine id for cohort overlay dims — matches backend OVERLAY_ID_RE. */
export const OVERLAY_ID_RE = /^[a-z][a-z0-9_]{0,63}$/;

export function normalizeOverlayId(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/-/g, "_")
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
}

export function suggestOverlayId(label?: string): string {
  const slug = normalizeOverlayId(label ?? "");
  return OVERLAY_ID_RE.test(slug) ? slug : "";
}

export function filtersForSampleApi(
  filters: PersonaDimensionFilters,
): Record<string, string | string[]> | undefined {
  const entries = Object.entries(filters.dimensionFilters).filter(([, values]) => values.length > 0);
  if (entries.length === 0) return undefined;
  return Object.fromEntries(entries.map(([key, values]) => [key, values.length === 1 ? values[0] : values]));
}

export interface StrategySamplingView {
  mode: PersonaSamplingMode;
  fields: string[];
  allocation: StratifiedAllocation;
  sampleSize: number | null;
  perCell: number | null;
}

function asSamplingMode(value: string | null | undefined): PersonaSamplingMode {
  if (value === "random" || value === "stratified" || value === "all" || value === "single") {
    return value;
  }
  return "single";
}

function asAllocation(
  value: string | null | undefined,
  fallback: StratifiedAllocation,
): StratifiedAllocation {
  if (value === "perCell" || value === "proportional" || value === "equalTotal") {
    return value;
  }
  return fallback;
}

/** Read the unified ``strategy.sampling`` block (required on valid strategies). */
export function readStrategySampling(
  strategy: TaskPersonaStrategy | null | undefined,
): StrategySamplingView {
  const sampling = strategy?.sampling;
  if (sampling && typeof sampling === "object") {
    const mode = asSamplingMode(sampling.mode);
    const fields = Array.isArray(sampling.fields)
      ? sampling.fields.filter(
          (field): field is string => typeof field === "string" && Boolean(field.trim()),
        )
      : [];
  const sampleSize =
    typeof sampling.sampleSize === "number" && sampling.sampleSize > 0
      ? Math.round(sampling.sampleSize)
      : typeof (sampling as { sample_size?: number }).sample_size === "number"
        ? Math.round((sampling as { sample_size?: number }).sample_size as number)
        : null;
  const perCell =
    typeof sampling.perCell === "number" && sampling.perCell >= 1
      ? Math.round(sampling.perCell)
      : typeof (sampling as { per_cell?: number }).per_cell === "number"
        ? Math.round((sampling as { per_cell?: number }).per_cell as number)
        : null;
    const allocationFallback: StratifiedAllocation =
      perCell != null ? "perCell" : sampleSize != null ? "equalTotal" : "perCell";
    return {
      mode: mode === "single" && fields.length > 0 ? "stratified" : mode,
      fields,
      allocation: asAllocation(sampling.allocation, allocationFallback),
      sampleSize,
      perCell,
    };
  }

  const legacy = strategy as
    | (TaskPersonaStrategy & {
        defaultMode?: string;
        stratifyFields?: string[];
        sampleSizePerValueGroup?: number;
        sampleSize?: number;
      })
    | null
    | undefined;
  const fields = Array.isArray(legacy?.stratifyFields)
    ? legacy.stratifyFields.filter(
        (field): field is string => typeof field === "string" && Boolean(field.trim()),
      )
    : [];
  const perCell =
    typeof legacy?.sampleSizePerValueGroup === "number" && legacy.sampleSizePerValueGroup >= 1
      ? Math.round(legacy.sampleSizePerValueGroup)
      : null;
  const sampleSize =
    typeof legacy?.sampleSize === "number" && legacy.sampleSize > 0
      ? Math.round(legacy.sampleSize)
      : null;
  const mode = asSamplingMode(legacy?.defaultMode);
  return {
    mode: fields.length > 0 ? "stratified" : mode,
    fields,
    allocation: perCell != null ? "perCell" : sampleSize != null ? "equalTotal" : "perCell",
    sampleSize,
    perCell,
  };
}
