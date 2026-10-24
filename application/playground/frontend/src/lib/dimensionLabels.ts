/**
 * Display-label overlay for persona dimensions.
 *
 * Canonical dimension ids and enum values stay English everywhere data is
 * stored, filtered, stratified, or scored. This module only swaps what the
 * operator sees: when the UI locale has a committed label pack
 * (persona/schema/labels/dimensions.labels.<locale>.json), lookups return the
 * translated strings; anything untranslated falls back to English.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useI18n } from "@/i18n/I18nProvider";
import { SOURCE_LOCALE } from "@/i18n/source";
import { api } from "./api";
import type { PersonaDimensionLabels } from "./types";

export interface DimensionLabelLookup {
  /** True when a non-English pack is loaded and non-empty. */
  active: boolean;
  /** Translated dimension label, or the given English fallback. */
  dimLabel: (dimId: string, fallback: string) => string;
  /** Translated enum value, or the raw English value. */
  valueLabel: (dimId: string, value: string) => string;
  /** Translated taxonomy group/subgroup title, or the English fallback. */
  taxonomyLabel: (nodeId: string, fallback: string) => string;
}

export function createDimensionLabelLookup(
  pack: PersonaDimensionLabels | null | undefined,
): DimensionLabelLookup {
  const dimensions = pack?.available ? pack.dimensions : undefined;
  const taxonomy = pack?.available ? pack.taxonomy : undefined;
  const active = Boolean(
    (dimensions && Object.keys(dimensions).length > 0) ||
      (taxonomy && Object.keys(taxonomy).length > 0),
  );
  return {
    active,
    dimLabel: (dimId, fallback) => dimensions?.[dimId]?.label || fallback,
    valueLabel: (dimId, value) => dimensions?.[dimId]?.values?.[value] || value,
    taxonomyLabel: (nodeId, fallback) => taxonomy?.[nodeId] || fallback,
  };
}

/** Label overlay for the active UI locale; inert English passthrough otherwise. */
export function useDimensionLabels(): DimensionLabelLookup {
  const { locale } = useI18n();
  const enabled = locale !== SOURCE_LOCALE;
  const query = useQuery({
    queryKey: ["persona-dimension-labels", locale],
    queryFn: () => api.getPersonaDimensionLabels(locale),
    enabled,
    staleTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
  });
  return useMemo(
    () => createDimensionLabelLookup(enabled ? query.data : null),
    [enabled, query.data],
  );
}
