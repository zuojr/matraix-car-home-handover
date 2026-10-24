import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";

import { useI18n } from "@/i18n/I18nProvider";
import type { MessageKey } from "@/i18n/types";
import { api } from "@/lib/api";
import {
  type DimensionLabelLookup,
  useDimensionLabels,
} from "@/lib/dimensionLabels";
import type { OverlayDimension } from "@/lib/types";
import type {
  PersonaMatchedAttribute,
  PersonaPoolCatalog,
  PersonaPoolDimensionGroup,
  PersonaPoolDimensionOption,
  PersonaPoolDimensionSubgroup,
} from "@/lib/types";
import { FOCUS_RING, Sym } from "../cockpitShared";
import {
  applyAllSuggestions,
  isSuggestionSelected,
  shouldMatchAttributes,
  suggestionKey,
  toggleSuggestionInFilters,
} from "./personaAttributeMatch";
import { OverlayDimensionDialog } from "./OverlayDimensionDialog";
import {
  collectCatalogDimIds,
  filterSelectionCounts,
  overlayCatalogGroup,
  setMarginalPercent,
  STUDY_OVERLAY_GROUP_ID,
  type PersonaDimensionFilters,
} from "./personaSamplingTypes";

/** Overlay-vs-filter copy variants — flat maps so i18n:check accepts `t(MAP[k])`. */
const FILTER_EMPTY_KEYS = {
  mix: "personaSetup.filters.noMix",
  filters: "personaSetup.filters.noFilters",
} as const satisfies Record<string, MessageKey>;

const FILTER_CLOSE_KEYS = {
  mix: "personaSetup.filters.closeMix",
  filters: "personaSetup.filters.close",
} as const satisfies Record<string, MessageKey>;

const FILTER_TITLE_KEYS = {
  mix: "personaSetup.filters.mixTitle",
  filters: "personaSetup.filters.title",
} as const satisfies Record<string, MessageKey>;

const FILTER_APPLY_KEYS = {
  mix: "personaSetup.filters.applyMix",
  filters: "personaSetup.filters.apply",
} as const satisfies Record<string, MessageKey>;

function overlayMode(allowOverlayEdit: boolean | undefined): "mix" | "filters" {
  return allowOverlayEdit ? "mix" : "filters";
}

export type PersonaMarginals = Record<string, Record<string, number>>;

export interface PersonaFilterModalProps {
  open: boolean;
  catalog: PersonaPoolCatalog | null;
  filters: PersonaDimensionFilters;
  stratifyMode?: boolean;
  fields?: string[];
  onFieldsChange?: (fields: string[]) => void;
  /** Edit per-dimension mix in the selected pane (generate · total). */
  showMarginals?: boolean;
  marginals?: PersonaMarginals;
  /** Cockpit persona model — used by Treiver LLM judge when enabled. */
  /** Generate-mode: add cohort-scoped study dimensions. */
  allowOverlayEdit?: boolean;
  overlayDimensions?: OverlayDimension[];
  /**
   * Right-hand selected / mix “basket” pane. Experiments often hide it;
   * forced on when ``showMarginals`` so By-share % stays editable.
   * @default true
   */
  showSelectedPane?: boolean;
  personaModel?: string;
  onClose: () => void;
  /**
   * ``marginals`` carries the per-dimension By-share mix when ``showMarginals``.
   * ``overlay`` is the updated cohort-scoped study dimensions when
   * ``allowOverlayEdit``. Both are omitted for Dataset / store filter modals.
   */
  onConfirm: (
    filters: PersonaDimensionFilters,
    marginals?: PersonaMarginals,
    overlay?: OverlayDimension[],
  ) => void;
}

function poolLabel(pool: string | undefined): string {
  if (!pool) return "";
  return pool.split("/").filter(Boolean).pop() || pool;
}

function dimLabel(dim: PersonaPoolDimensionOption): string {
  return (dim.label || dim.id.replace(/_/g, " ")).trim();
}

function findDimensionLabel(
  catalog: PersonaPoolCatalog | null,
  dimId: string,
  labels?: DimensionLabelLookup,
): string {
  const groups = catalog?.dimensionCategories?.devProfile?.groups ?? [];
  for (const group of groups) {
    for (const dim of group.dimensions ?? []) {
      if (dim.id === dimId) {
        return labels?.dimLabel(dim.id, dimLabel(dim)) ?? dimLabel(dim);
      }
    }
    for (const sub of group.subgroups ?? []) {
      for (const dim of sub.dimensions ?? []) {
        if (dim.id === dimId) {
          return labels?.dimLabel(dim.id, dimLabel(dim)) ?? dimLabel(dim);
        }
      }
    }
  }
  const fallback = dimId.replace(/_/g, " ");
  return labels?.dimLabel(dimId, fallback) ?? fallback;
}

type FilterChipGroup = {
  dimId: string;
  label: string;
  chips: Array<{ key: string; value: string; displayValue: string }>;
};

function chipGroupsFromFilters(
  filters: PersonaDimensionFilters,
  options: {
    includeSources: boolean;
    overlay: OverlayDimension[];
    catalog: PersonaPoolCatalog | null;
    labels: DimensionLabelLookup;
    sourceLabel: string;
  },
): FilterChipGroup[] {
  const groups: FilterChipGroup[] = [];
  if (options.includeSources && filters.sources.length > 0) {
    groups.push({
      dimId: "source",
      label: options.sourceLabel,
      chips: filters.sources.map((source) => ({
        key: `source:${source}`,
        value: source,
        displayValue: source,
      })),
    });
  }
  for (const [dimId, values] of Object.entries(filters.dimensionFilters)) {
    if (values.length === 0) continue;
    groups.push({
      dimId,
      label:
        options.overlay.find((dim) => dim.id === dimId)?.label ||
        findDimensionLabel(options.catalog, dimId, options.labels),
      chips: values.map((value) => ({
        key: `${dimId}:${value}`,
        value,
        displayValue: options.labels.valueLabel(dimId, value),
      })),
    });
  }
  return groups;
}

function matchesQuery(text: string, query: string): boolean {
  if (!query) return true;
  return text.toLowerCase().includes(query);
}

function dimensionMatchesQuery(
  dim: PersonaPoolDimensionOption,
  query: string,
  labels?: DimensionLabelLookup,
): boolean {
  if (!query) return true;
  const display = labels?.dimLabel(dim.id, dimLabel(dim)) ?? dimLabel(dim);
  if (matchesQuery(`${display} ${dimLabel(dim)} ${dim.id}`, query)) return true;
  return (dim.values ?? []).some((value) =>
    matchesQuery(
      `${value} ${labels?.valueLabel(dim.id, value) ?? value}`,
      query,
    ),
  );
}

function filterDimensionValues(
  dim: PersonaPoolDimensionOption,
  query: string,
  labels?: DimensionLabelLookup,
): string[] {
  const values = dim.values ?? [];
  if (!query) return values;
  const display = labels?.dimLabel(dim.id, dimLabel(dim)) ?? dimLabel(dim);
  if (matchesQuery(`${display} ${dimLabel(dim)} ${dim.id}`, query)) return values;
  return values.filter((value) =>
    matchesQuery(
      `${value} ${labels?.valueLabel(dim.id, value) ?? value}`,
      query,
    ),
  );
}

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

function groupDisplayLabel(
  group: PersonaPoolDimensionGroup,
  labels: DimensionLabelLookup,
  overlayGroupLabel: string,
): string {
  if (group.id === STUDY_OVERLAY_GROUP_ID) {
    return overlayGroupLabel;
  }
  return labels.taxonomyLabel(group.id, group.label);
}

function groupDimensionIds(group: PersonaPoolDimensionGroup): string[] {
  const subgroups = group.subgroups ?? [];
  if (subgroups.length > 0) {
    return subgroups.flatMap((sub) => (sub.dimensions ?? []).map((dim) => dim.id));
  }
  return (group.dimensions ?? []).map((dim) => dim.id);
}

function selectedAttrCount(
  filters: PersonaDimensionFilters,
  dimIds: string[],
): number {
  let n = 0;
  for (const id of dimIds) n += filters.dimensionFilters[id]?.length ?? 0;
  return n;
}

type FilterJumpTarget = {
  groupId: string;
  subgroupId?: string | null;
  dimId?: string | null;
};

function filterAnchorId(target: FilterJumpTarget): string {
  if (target.dimId) return `pf-dim-${target.dimId}`;
  if (target.subgroupId) return `pf-sub-${target.subgroupId}`;
  return `pf-group-${target.groupId}`;
}

export function PersonaFilterModal({
  open,
  catalog,
  filters,
  stratifyMode = false,
  fields = [],
  onFieldsChange,
  showMarginals = false,
  marginals,
  allowOverlayEdit = false,
  overlayDimensions,
  showSelectedPane = true,
  personaModel,
  onClose,
  onConfirm,
}: PersonaFilterModalProps) {
  const { t, locale } = useI18n();
  const labels = useDimensionLabels();
  const [draft, setDraft] = useState(filters);
  const [draftMarginals, setDraftMarginals] = useState<PersonaMarginals>(
    () => marginals ?? {},
  );
  const [draftOverlay, setDraftOverlay] = useState<OverlayDimension[]>(
    () => overlayDimensions ?? [],
  );
  const [overlayDialogOpen, setOverlayDialogOpen] = useState(false);
  const [percentDraft, setPercentDraft] = useState<{
    dim: string;
    value: string;
    text: string;
  } | null>(null);
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const [expandedSubgroup, setExpandedSubgroup] = useState<string | null>(null);
  const [expandedDim, setExpandedDim] = useState<string | null>(null);
  const [treeCollapsedGroups, setTreeCollapsedGroups] = useState<Set<string>>(
    new Set(),
  );
  const [treeExpandedSubs, setTreeExpandedSubs] = useState<Set<string>>(
    new Set(),
  );
  const pendingScrollId = useRef<string | null>(null);
  const pendingRevealKey = useRef<string | null>(null);
  const [query, setQuery] = useState("");
  const [searchTier, setSearchTier] = useState<"keyword" | "keyword_and_embed">(
    "keyword",
  );
  const [deepMatch, setDeepMatch] = useState(false);
  const debouncedQuery = useDebounced(query.trim(), 280);
  const matchEnabled = open && shouldMatchAttributes(debouncedQuery);
  const searchMode =
    searchTier === "keyword"
      ? "keyword"
      : deepMatch
        ? "keyword_and_embed_and_llm"
        : "keyword_and_embed";
  const modelShort = (personaModel || "")
    .split("/")
    .filter(Boolean)
    .pop();

  const matchQuery = useQuery({
    queryKey: [
      "persona-pool-match-attributes",
      debouncedQuery,
      searchMode,
      locale,
      personaModel ?? "",
    ],
    queryFn: () =>
      api.matchPersonaAttributes(debouncedQuery, {
        searchMode,
        locale,
        personaModel,
      }),
    enabled: matchEnabled,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const suggestions: PersonaMatchedAttribute[] =
    matchQuery.data?.attributes ?? [];
  const resultMode = matchQuery.data?.searchMode ?? searchMode;
  const judgeModel =
    matchQuery.data?.judgeModel || personaModel || undefined;
  const suggestedDimIds = useMemo(() => {
    const fromApi = matchQuery.data?.suggestedDimensionIds;
    if (Array.isArray(fromApi) && fromApi.length > 0) {
      return new Set(fromApi);
    }
    return new Set(suggestions.map((attr) => attr.dimensionId));
  }, [matchQuery.data?.suggestedDimensionIds, suggestions]);

  useEffect(() => {
    if (open) {
      setDraft(filters);
      setDraftMarginals(marginals ?? {});
      setDraftOverlay(overlayDimensions ?? []);
      setOverlayDialogOpen(false);
      setPercentDraft(null);
      setQuery("");
      setSearchTier("keyword");
      setDeepMatch(false);
      setExpandedGroup(null);
      setExpandedSubgroup(null);
      setExpandedDim(null);
      setTreeCollapsedGroups(new Set());
      setTreeExpandedSubs(new Set());
      pendingScrollId.current = null;
      pendingRevealKey.current = null;
    }
  }, [open, filters, marginals, overlayDimensions]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  const sources = useMemo(() => {
    const fromCategories = catalog?.dimensionCategories?.personaSources ?? [];
    if (fromCategories.length > 0) return fromCategories;
    return Object.keys(catalog?.sourceCounts ?? {});
  }, [catalog]);

  const groups = useMemo(() => {
    const base = catalog?.dimensionCategories?.devProfile?.groups ?? [];
    if (!allowOverlayEdit) return base;
    const withoutOverlay = base.filter(
      (group) => group.id !== STUDY_OVERLAY_GROUP_ID,
    );
    if (draftOverlay.length === 0) return withoutOverlay;
    return [
      overlayCatalogGroup(
        draftOverlay,
        t("personaSetup.filters.overlayGroup"),
      ),
      ...withoutOverlay,
    ];
  }, [allowOverlayEdit, catalog, draftOverlay, t]);

  const catalogDimIds = useMemo(
    () => collectCatalogDimIds(catalog),
    [catalog],
  );

  /** Basket stays for By-share % even when callers hide the empty cart. */
  const selectedPaneVisible = showSelectedPane || showMarginals;

  const activeFilters = draft;
  const normalizedQuery = query.trim().toLowerCase();

  const visibleGroups = useMemo(() => {
    if (!normalizedQuery) return groups;
    const smartHint =
      searchTier === "keyword_and_embed" && suggestedDimIds.size > 0
        ? suggestedDimIds
        : null;
    const next: PersonaPoolDimensionGroup[] = [];
    for (const group of groups) {
      const subgroups = group.subgroups ?? [];
      if (subgroups.length > 0) {
        const matchedSubs: PersonaPoolDimensionSubgroup[] = [];
        for (const sub of subgroups) {
          const dims = (sub.dimensions ?? []).filter(
            (dim) =>
              dimensionMatchesQuery(dim, normalizedQuery, labels) ||
              Boolean(smartHint?.has(dim.id)),
          );
          if (dims.length === 0) continue;
          matchedSubs.push({
            ...sub,
            dimensions: dims,
            dimensionIds: dims.map((d) => d.id),
          });
        }
        if (matchedSubs.length === 0) continue;
        next.push({
          ...group,
          subgroups: matchedSubs,
          dimensions: matchedSubs.flatMap((s) => s.dimensions),
          dimensionIds: matchedSubs.flatMap((s) => s.dimensionIds),
        });
        continue;
      }
      const dims = (group.dimensions ?? []).filter(
        (dim) =>
          dimensionMatchesQuery(dim, normalizedQuery, labels) ||
          Boolean(smartHint?.has(dim.id)),
      );
      if (dims.length === 0) continue;
      next.push({
        ...group,
        dimensions: dims,
        dimensionIds: dims.map((d) => d.id),
      });
    }
    return next;
  }, [groups, labels, normalizedQuery, searchTier, suggestedDimIds]);

  const selectedGroups = useMemo(
    () =>
      chipGroupsFromFilters(activeFilters, {
        includeSources: true,
        overlay: draftOverlay,
        catalog,
        labels,
        sourceLabel: t("personaSetup.filters.source"),
      }),
    [activeFilters, catalog, draftOverlay, labels, t],
  );

  useEffect(() => {
    const id = pendingScrollId.current;
    if (!id) return;
    pendingScrollId.current = null;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        document.getElementById(id)?.scrollIntoView({
          block: "nearest",
          behavior: "smooth",
        });
      });
    });
  }, [expandedGroup, expandedSubgroup, expandedDim]);

  useEffect(() => {
    const key = pendingRevealKey.current;
    if (!key || !open) return;
    pendingRevealKey.current = null;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const target =
          key === "__bottom"
            ? document.getElementById("pf-sel-end")
            : document.getElementById(`pf-sel-${key}`);
        target?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    });
  }, [activeFilters, open]);

  if (!open) return null;

  const toggleTreeGroup = (id: string) => {
    setTreeCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleTreeSub = (id: string) => {
    setTreeExpandedSubs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const jumpTo = (target: FilterJumpTarget) => {
    setExpandedGroup(target.groupId);
    setExpandedSubgroup(target.subgroupId ?? null);
    setExpandedDim(target.dimId ?? null);
    setTreeCollapsedGroups((prev) => {
      if (!prev.has(target.groupId)) return prev;
      const next = new Set(prev);
      next.delete(target.groupId);
      return next;
    });
    if (target.subgroupId) {
      setTreeExpandedSubs((prev) => {
        if (prev.has(target.subgroupId!)) return prev;
        const next = new Set(prev);
        next.add(target.subgroupId!);
        return next;
      });
    }
    pendingScrollId.current = filterAnchorId(target);
  };

  const treeRowClass = (active: boolean, selected: boolean) =>
    `flex w-full cursor-pointer items-center gap-1 rounded-md px-1.5 py-1 text-left transition-colors duration-200 ${FOCUS_RING} ${
      active
        ? "bg-primary/15 text-primary"
        : selected
          ? "text-primary hover:bg-surface-high/50"
          : "text-text-variant hover:bg-surface-high/40 hover:text-text-main"
    }`;

  const renderDirectory = () => (
    <nav
      aria-label={t("personaSetup.filters.directory")}
      className="custom-scrollbar hidden min-h-0 w-56 shrink-0 overflow-y-auto border-r border-outline/30 bg-surface/20 px-2 py-2 md:block"
    >
      <p className="mb-1.5 px-1.5 text-[10px] font-medium uppercase tracking-wide text-text-dim">
        {t("personaSetup.filters.directory")}
      </p>
      <ul className="space-y-0.5">
        {visibleGroups.map((group) => {
          const groupOpen =
            !treeCollapsedGroups.has(group.id) || Boolean(normalizedQuery);
          const subgroups = group.subgroups ?? [];
          const groupCount = selectedAttrCount(activeFilters, groupDimensionIds(group));
          const groupActive = expandedGroup === group.id;
          return (
            <li key={group.id}>
              <div className="flex items-center">
                <button
                  type="button"
                  aria-expanded={groupOpen}
                  onClick={() => toggleTreeGroup(group.id)}
                  className={`shrink-0 cursor-pointer rounded p-0.5 text-text-dim hover:bg-surface-high/50 ${FOCUS_RING}`}
                >
                  <Sym
                    name={groupOpen ? "expand_more" : "chevron_right"}
                    size={14}
                  />
                </button>
                <button
                  type="button"
                  onClick={() => jumpTo({ groupId: group.id })}
                  className={`${treeRowClass(groupActive && !expandedSubgroup && !expandedDim, groupCount > 0)} min-w-0 flex-1 text-[12px] font-medium`}
                >
                  <span className="truncate">
                    {groupDisplayLabel(
                      group,
                      labels,
                      t("personaSetup.filters.overlayGroup"),
                    )}
                  </span>
                  {groupCount > 0 ? (
                    <span className="ml-auto shrink-0 font-mono text-[10px] text-primary">
                      {groupCount}
                    </span>
                  ) : null}
                </button>
              </div>
              {groupOpen ? (
                <ul className="ml-3 border-l border-outline/25 pl-1.5">
                  {subgroups.length > 0
                    ? subgroups.map((sub) => {
                        const subOpen =
                          treeExpandedSubs.has(sub.id) ||
                          Boolean(normalizedQuery);
                        const subCount = selectedAttrCount(
                          activeFilters,
                          (sub.dimensions ?? []).map((dim) => dim.id),
                        );
                        const subActive = expandedSubgroup === sub.id;
                        return (
                          <li key={sub.id}>
                            <div className="flex items-center">
                              <button
                                type="button"
                                aria-expanded={subOpen}
                                onClick={() => toggleTreeSub(sub.id)}
                                className={`shrink-0 cursor-pointer rounded p-0.5 text-text-dim hover:bg-surface-high/50 ${FOCUS_RING}`}
                              >
                                <Sym
                                  name={subOpen ? "expand_more" : "chevron_right"}
                                  size={14}
                                />
                              </button>
                              <button
                                type="button"
                                onClick={() =>
                                  jumpTo({
                                    groupId: group.id,
                                    subgroupId: sub.id,
                                  })
                                }
                                className={`${treeRowClass(subActive && !expandedDim, subCount > 0)} min-w-0 flex-1 text-[12px]`}
                              >
                                <span className="truncate">
                                  {labels.taxonomyLabel(sub.id, sub.label)}
                                </span>
                                {subCount > 0 ? (
                                  <span className="ml-auto shrink-0 font-mono text-[10px] text-primary">
                                    {subCount}
                                  </span>
                                ) : null}
                              </button>
                            </div>
                            {subOpen ? (
                              <ul className="ml-3 border-l border-outline/20 pl-1">
                                {(sub.dimensions ?? []).map((dim) => {
                                  const dimCount =
                                    activeFilters.dimensionFilters[dim.id]
                                      ?.length ?? 0;
                                  return (
                                    <li key={dim.id}>
                                      <button
                                        type="button"
                                        title={labels.dimLabel(
                                          dim.id,
                                          dimLabel(dim),
                                        )}
                                        onClick={() =>
                                          jumpTo({
                                            groupId: group.id,
                                            subgroupId: sub.id,
                                            dimId: dim.id,
                                          })
                                        }
                                        className={`${treeRowClass(expandedDim === dim.id, dimCount > 0)} w-full text-[11px]`}
                                      >
                                        <span className="truncate">
                                          {labels.dimLabel(dim.id, dimLabel(dim))}
                                        </span>
                                        {dimCount > 0 ? (
                                          <span className="ml-auto shrink-0 font-mono text-[10px] text-primary">
                                            {dimCount}
                                          </span>
                                        ) : null}
                                      </button>
                                    </li>
                                  );
                                })}
                              </ul>
                            ) : null}
                          </li>
                        );
                      })
                    : (group.dimensions ?? []).map((dim) => {
                        const dimCount =
                          activeFilters.dimensionFilters[dim.id]?.length ?? 0;
                        return (
                          <li key={dim.id}>
                            <button
                              type="button"
                              title={labels.dimLabel(dim.id, dimLabel(dim))}
                              onClick={() =>
                                jumpTo({ groupId: group.id, dimId: dim.id })
                              }
                              className={`${treeRowClass(expandedDim === dim.id, dimCount > 0)} w-full text-[11px]`}
                            >
                              <span className="truncate">
                                {labels.dimLabel(dim.id, dimLabel(dim))}
                              </span>
                              {dimCount > 0 ? (
                                <span className="ml-auto shrink-0 font-mono text-[10px] text-primary">
                                  {dimCount}
                                </span>
                              ) : null}
                            </button>
                          </li>
                        );
                      })}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </nav>
  );

  const renderOverlayAddButton = (className = "") =>
    allowOverlayEdit ? (
      <button
        type="button"
        onClick={() => setOverlayDialogOpen(true)}
        className={`inline-flex h-8 shrink-0 cursor-pointer items-center gap-1 rounded-lg bg-primary px-2.5 text-[12px] font-medium text-on-primary hover:opacity-90 ${FOCUS_RING} ${className}`}
      >
        <Sym name="add" size={16} />
        {t("personaSetup.filters.overlayAdd")}
      </button>
    ) : null;

  const renderSelected = () => {
    return (
    <aside
      aria-label={
        allowOverlayEdit
          ? t("personaSetup.filters.thisDataset")
          : t("personaSetup.filters.selected")
      }
      className="flex min-h-[12rem] w-full shrink-0 flex-col border-t border-outline/30 bg-surface/20 md:min-h-0 md:w-[26rem] md:border-l md:border-t-0 xl:w-[28rem]"
    >
      {allowOverlayEdit ? (
      <div className="shrink-0 border-b border-outline/25 px-3 py-2.5">
        <p className="text-[12px] text-text-variant">
          {selectedGroups.length > 0
            ? t(
                "personaSetup.filters.filterCount",
                filterSelectionCounts(activeFilters),
              )
            : t(FILTER_EMPTY_KEYS[overlayMode(allowOverlayEdit)])}
          {stratifyMode ? (
            <>
              {" "}
              ·{" "}
              {t("personaSetup.filters.stratifyAxisCount", {
                count: fields.length,
              })}
            </>
          ) : null}
        </p>
        {showMarginals &&
        selectedGroups.some((g) => g.dimId !== "source") ? (
          <p className="mt-1 text-[12px] text-text-dim">
            {t("personaSetup.filters.marginalsHint")}
          </p>
        ) : null}
      </div>
      ) : (
      <div className="shrink-0 border-b border-outline/25 px-3 py-2.5">
        <p className="text-[11px] font-medium uppercase tracking-wide text-text-dim">
          {t("personaSetup.filters.selected")}
        </p>
        <p className="mt-0.5 text-[12px] text-text-variant">
          {selectedGroups.length > 0
            ? t(
                "personaSetup.filters.filterCount",
                filterSelectionCounts(activeFilters),
              )
            : t(FILTER_EMPTY_KEYS[overlayMode(allowOverlayEdit)])}
          {stratifyMode ? (
            <>
              {" "}
              ·{" "}
              {t("personaSetup.filters.stratifyAxisCount", {
                count: fields.length,
              })}
            </>
          ) : null}
        </p>
      </div>
      )}
      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-2.5">
        {selectedGroups.length === 0 && !stratifyMode ? (
          <p className="text-[13px] leading-relaxed text-text-dim">
            {t(FILTER_EMPTY_KEYS[overlayMode(allowOverlayEdit)])}
          </p>
        ) : (
          <div className="space-y-3">
            {selectedGroups.map((group) => {
              const values = group.chips.map((chip) => chip.value);
              const weights = values.map(
                (value) => draftMarginals[group.dimId]?.[value] ?? 1,
              );
              const total = weights.reduce((sum, w) => sum + w, 0);
              const editMix = showMarginals && group.dimId !== "source";
              return (
              <div
                id={`pf-sel-group-${group.dimId}`}
                key={group.dimId}
                className="space-y-1.5"
              >
                <p className="text-[12px] text-text-dim">{group.label}</p>
                {editMix ? (
                  <div className="space-y-1">
                    {group.chips.map((chip, index) => {
                      const pct =
                        total > 0
                          ? Math.round((100 * (weights[index] ?? 1)) / total)
                          : 0;
                      const drafting =
                        percentDraft?.dim === group.dimId &&
                        percentDraft.value === chip.value;
                      return (
                        <div
                          id={`pf-sel-${chip.key}`}
                          key={chip.key}
                          className="flex items-center gap-2"
                        >
                          <button
                            type="button"
                            onClick={() =>
                              removeChip({
                                key: chip.key,
                                dimId: group.dimId,
                                label: group.label,
                                value: chip.value,
                              })
                            }
                            className="glass-tile glass-tile--active inline-flex min-w-0 flex-1 cursor-pointer items-center gap-1 rounded-full px-2.5 py-1 text-left text-[12px] text-primary"
                          >
                            <span className="min-w-0 truncate">
                              {chip.displayValue}
                            </span>
                            <Sym name="close" size={12} className="shrink-0" />
                          </button>
                          <span className="flex shrink-0 items-center gap-0.5">
                            <input
                              type="number"
                              min={0}
                              max={100}
                              step={1}
                              aria-label={`${chip.displayValue} %`}
                              value={drafting ? percentDraft.text : pct}
                              onFocus={() =>
                                setPercentDraft({
                                  dim: group.dimId,
                                  value: chip.value,
                                  text: String(pct),
                                })
                              }
                              onChange={(e) => {
                                const raw = e.target.value;
                                if (raw === "" || /^\d{0,3}$/.test(raw)) {
                                  setPercentDraft({
                                    dim: group.dimId,
                                    value: chip.value,
                                    text: raw,
                                  });
                                }
                              }}
                              onBlur={() => {
                                const raw = percentDraft?.text;
                                setPercentDraft(null);
                                const next = Number(raw);
                                if (!Number.isFinite(next)) return;
                                setDraftMarginals((prev) =>
                                  setMarginalPercent(
                                    prev,
                                    group.dimId,
                                    values,
                                    chip.value,
                                    next,
                                  ),
                                );
                              }}
                              className={`h-7 w-11 rounded border border-outline/50 bg-surface/80 px-1 text-center font-mono text-[13px] font-medium text-text-main ${FOCUS_RING}`}
                            />
                            <span className="w-3 text-[12px] font-medium text-text-main">
                              %
                            </span>
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                <div className="flex flex-wrap gap-1.5">
                  {group.chips.map((chip) => (
                    <button
                      id={`pf-sel-${chip.key}`}
                      key={chip.key}
                      type="button"
                      onClick={() =>
                        removeChip({
                          key: chip.key,
                          dimId: group.dimId,
                          label: group.label,
                          value: chip.value,
                        })
                      }
                      className="glass-tile glass-tile--active inline-flex cursor-pointer items-center gap-1 rounded-full px-2.5 py-1 text-[12px] text-primary"
                    >
                      {chip.displayValue}
                      <Sym name="close" size={12} />
                    </button>
                  ))}
                </div>
                )}
              </div>
              );
            })}
            {stratifyMode ? (
              <div className="space-y-1.5">
                <p className="text-[12px] text-text-dim">
                  {t("personaSetup.filters.stratifyAxes", {
                    count: fields.length,
                  })}
                </p>
                {fields.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {fields.map((field) => {
                      const label = findDimensionLabel(catalog, field, labels);
                      return (
                        <button
                          key={field}
                          type="button"
                          onClick={() => toggleStratifyField(field)}
                          className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-secondary/40 bg-secondary/10 px-2.5 py-1 text-[12px] text-secondary"
                        >
                          {t("personaSetup.filters.stratify")} · {label}
                          <Sym name="close" size={12} />
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-[13px] text-text-dim">
                    {t("personaSetup.filters.stratifyHint")}
                  </p>
                )}
              </div>
            ) : null}
            <div id="pf-sel-end" />
          </div>
        )}
      </div>
    </aside>
  );
  };

  const toggleSource = (source: string) => {
    setDraft((prev) => {
      const adding = !prev.sources.includes(source);
      if (adding) pendingRevealKey.current = `source:${source}`;
      return {
        ...prev,
        sources: adding
          ? [...prev.sources, source]
          : prev.sources.filter((item) => item !== source),
      };
    });
  };

  const addOverlayDimensions = (added: OverlayDimension[]) => {
    if (added.length === 0) return;
    // Dimension is added to the catalog only — attributes stay unselected until picked.
    setDraftOverlay((prev) => [...prev, ...added]);
    const last = added[added.length - 1];
    setExpandedGroup(STUDY_OVERLAY_GROUP_ID);
    setExpandedDim(last.id);
    pendingScrollId.current = `pf-dim-${last.id}`;
  };

  const removeOverlayDimension = (dimId: string) => {
    setDraftOverlay((prev) => prev.filter((dim) => dim.id !== dimId));
    setDraft((prev) => {
      const nextFilters = { ...prev.dimensionFilters };
      delete nextFilters[dimId];
      return { ...prev, dimensionFilters: nextFilters };
    });
    setDraftMarginals((prev) => {
      if (!(dimId in prev)) return prev;
      const next = { ...prev };
      delete next[dimId];
      return next;
    });
  };

  const toggleFilterValue = (
    setter: (
      update: (prev: PersonaDimensionFilters) => PersonaDimensionFilters,
    ) => void,
    dimId: string,
    value: string,
  ) => {
    setter((prev) => {
      const current = prev.dimensionFilters[dimId] ?? [];
      const adding = !current.includes(value);
      if (adding) pendingRevealKey.current = `${dimId}:${value}`;
      const nextValues = adding
        ? [...current, value]
        : current.filter((item) => item !== value);
      const nextFilters = { ...prev.dimensionFilters };
      if (nextValues.length === 0) delete nextFilters[dimId];
      else nextFilters[dimId] = nextValues;
      return { ...prev, dimensionFilters: nextFilters };
    });
  };

  const toggleDimensionValue = (dimId: string, value: string) => {
    toggleFilterValue(setDraft, dimId, value);
  };

  const removeChip = (chip: {
    key: string;
    dimId: string;
    label: string;
    value: string;
  }) => {
    if (chip.dimId === "source") {
      setDraft((prev) => ({
        ...prev,
        sources: prev.sources.filter((item) => item !== chip.value),
      }));
      return;
    }
    toggleFilterValue(setDraft, chip.dimId, chip.value);
  };

  const toggleStratifyField = (dimId: string) => {
    if (!onFieldsChange) return;
    const next = fields.includes(dimId)
      ? fields.filter((item) => item !== dimId)
      : [...fields, dimId];
    onFieldsChange(next);
  };

  const renderDimension = (dim: PersonaPoolDimensionOption) => {
    const visibleValues = filterDimensionValues(dim, normalizedQuery, labels);
    const dimOpen =
      expandedDim === dim.id ||
      (Boolean(normalizedQuery) && visibleValues.length > 0);
    const selected = activeFilters.dimensionFilters[dim.id] ?? [];
    const stratified = fields.includes(dim.id);
    const displayName = labels.dimLabel(dim.id, dimLabel(dim));
    const overlayDim = draftOverlay.some((row) => row.id === dim.id) ||
      groups.some(
        (group) =>
          group.id === STUDY_OVERLAY_GROUP_ID &&
          (group.dimensions ?? []).some((item) => item.id === dim.id),
      );
    return (
      <div
        id={`pf-dim-${dim.id}`}
        key={dim.id}
        className="scroll-mt-2 rounded-md border border-outline/30 bg-surface/20"
      >
        <button
          type="button"
          onClick={() =>
            setExpandedDim(dimOpen && !normalizedQuery ? null : dim.id)
          }
          className={`flex w-full items-center justify-between gap-2 px-2.5 py-2 text-left text-[13px] ${FOCUS_RING}`}
        >
          <span className={selected.length ? "text-primary" : "text-text-main"}>
            {displayName}
            {selected.length > 0 ? ` · ${selected.length}` : ""}
            {overlayDim ? (
              <span className="ml-1.5 font-mono text-[11px] font-normal text-text-dim">
                {dim.id}
              </span>
            ) : null}
          </span>
          <div className="flex items-center gap-2">
            {allowOverlayEdit && overlayDim ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  removeOverlayDimension(dim.id);
                }}
                className={`rounded-full border border-outline/40 px-2 py-0.5 text-[11px] text-text-dim hover:border-danger/40 hover:text-danger ${FOCUS_RING}`}
              >
                {t("personaSetup.filters.overlayRemove")}
              </button>
            ) : null}
            {stratifyMode && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleStratifyField(dim.id);
                }}
                className={`rounded-full border px-2 py-0.5 text-[11px] ${
                  stratified
                    ? "border-secondary/40 bg-secondary/10 text-secondary"
                    : "border-outline/40 text-text-dim"
                }`}
              >
                {t("personaSetup.filters.stratify")}
              </button>
            )}
            <Sym
              name={dimOpen ? "expand_less" : "expand_more"}
              size={16}
              className="text-text-dim"
            />
          </div>
        </button>
        {dimOpen && (
          <div className="flex flex-wrap gap-1.5 border-t border-outline/20 px-2.5 py-2">
            {visibleValues.map((value) => {
              const active = selected.includes(value);
              return (
                <button
                  key={value}
                  type="button"
                  onClick={() => toggleDimensionValue(dim.id, value)}
                  className={`rounded-full px-2.5 py-1 text-[12px] ${FOCUS_RING} ${
                    active
                      ? "glass-tile glass-tile--active text-primary"
                      : "glass-tile glass-tile--hover text-text-variant"
                  }`}
                >
                  {labels.valueLabel(dim.id, value)}
                </button>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  const matchErrorMessage =
    matchQuery.isError && matchQuery.error instanceof Error
      ? matchQuery.error.message
      : matchQuery.isError
        ? String(matchQuery.error)
        : null;

  const showEmptyTree =
    Boolean(normalizedQuery) &&
    visibleGroups.length === 0 &&
    suggestions.length === 0 &&
    !matchQuery.isFetching &&
    !matchErrorMessage;
  const datasetName =
    poolLabel(catalog?.pool) || t("personaSetup.filters.defaultPool");

  return (
    <>
  {createPortal(
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-2 sm:p-3">
      <button
        type="button"
        className="absolute inset-0 bg-surface-dim/75 backdrop-blur-sm"
        aria-label={t(FILTER_CLOSE_KEYS[overlayMode(allowOverlayEdit)])}
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="persona-filter-modal-title"
        className="glass-panel-strong relative z-10 flex h-[min(96vh,100dvh)] w-full max-w-[min(98vw,112rem)] flex-col overflow-hidden rounded-xl shadow-2xl"
      >
        <div className="flex items-center justify-between gap-3 border-b border-outline/40 px-5 py-4">
          <div className="min-w-0">
            <h2
              id="persona-filter-modal-title"
              className="font-display text-[18px] font-semibold text-text-main"
            >
              {t(FILTER_TITLE_KEYS[overlayMode(allowOverlayEdit)])}
            </h2>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={onClose}
              aria-label={t(FILTER_CLOSE_KEYS[overlayMode(allowOverlayEdit)])}
              className={`rounded-md p-2 text-text-variant hover:bg-surface-high ${FOCUS_RING}`}
            >
            <Sym name="close" size={20} />
          </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <div className="shrink-0 px-5 pt-3">
            {allowOverlayEdit ? null : (
          <div className="mb-3 space-y-3">
            <div>
              <p className="mb-1.5 text-[13px] text-text-variant">
                {t("personaSetup.dataset")}
              </p>
              <div className="flex flex-wrap gap-2">
                <span
                  className="glass-tile glass-tile--active rounded-full px-3 py-1.5 text-[13px] text-primary"
                  title={catalog?.pool || datasetName}
                >
                  {datasetName}
                  {typeof catalog?.count === "number"
                    ? ` · ${catalog.count.toLocaleString()}`
                    : ""}
                </span>
              </div>
            </div>
            <div>
              <p className="mb-1.5 text-[13px] text-text-variant">
                {t("personaSetup.filters.provenance")}
              </p>
              <div className="flex flex-wrap gap-2">
            {sources.map((source) => {
              const active = draft.sources.includes(source);
              const count = catalog?.sourceCounts?.[source];
              return (
                <button
                  key={source}
                  type="button"
                  onClick={() => toggleSource(source)}
                  className={`rounded-full px-3 py-1.5 text-[13px] transition ${FOCUS_RING} ${
                    active
                      ? "glass-tile glass-tile--active text-primary"
                      : "glass-tile glass-tile--hover text-text-variant"
                  }`}
                >
                  {source}
                      {typeof count === "number"
                        ? ` · ${count.toLocaleString()}`
                        : ""}
                </button>
              );
            })}
          </div>
            </div>
          </div>
            )}

          <div className="mb-3">
            <p className="mb-1.5 text-[13px] text-text-variant">
              {t("personaSetup.filters.profileDimensions")}
            </p>
            <div className="rounded-xl border border-outline/35 bg-surface/25 p-2.5">
              <label className="relative block">
              <Sym
                name="search"
                  size={17}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-dim"
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("personaSetup.filters.searchPlaceholder")}
                  className={`h-10 w-full rounded-lg border border-outline/45 bg-field pl-10 pr-3 text-[13px] text-text-main placeholder:text-text-dim ${FOCUS_RING}`}
              />
            </label>
              <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
                <div
                  role="group"
                  aria-label={t("personaSetup.filters.searchTier")}
                  className="inline-flex h-8 overflow-hidden rounded-lg border border-outline/40 bg-field/80"
                >
                  <button
                    type="button"
                    title={t("personaSetup.filters.searchKeywordHint")}
                    onClick={() => {
                      setSearchTier("keyword");
                      setDeepMatch(false);
                    }}
                    className={`px-3 text-[12px] transition ${FOCUS_RING} ${
                      searchTier === "keyword"
                        ? "bg-primary/15 font-medium text-primary"
                        : "text-text-variant hover:bg-surface-high/40"
                    }`}
                  >
                    {t("personaSetup.filters.searchKeyword")}
                  </button>
                  <button
                    type="button"
                    title={t("personaSetup.filters.searchSmartHint")}
                    onClick={() => setSearchTier("keyword_and_embed")}
                    className={`px-3 text-[12px] transition ${FOCUS_RING} ${
                      searchTier === "keyword_and_embed"
                        ? "bg-primary/15 font-medium text-primary"
                        : "text-text-variant hover:bg-surface-high/40"
                    }`}
                  >
                    {t("personaSetup.filters.searchSmart")}
                  </button>
                </div>
                {searchTier === "keyword_and_embed" ? (
                  <label
                    className={`inline-flex max-w-full cursor-pointer items-center gap-2 text-[12px] text-text-variant ${FOCUS_RING}`}
                    title={t("personaSetup.filters.searchDeepHint")}
                  >
                    <input
                      type="checkbox"
                      checked={deepMatch}
                      onChange={(e) => setDeepMatch(e.target.checked)}
                      className="rounded border-outline/60"
                    />
                    <span className="truncate">
                      {modelShort
                        ? t("personaSetup.filters.searchDeepWithModel", {
                            model: modelShort,
                          })
                        : t("personaSetup.filters.searchDeep")}
                    </span>
                  </label>
                ) : null}
          </div>

              {matchEnabled && matchQuery.isFetching ? (
                <p className="mt-2.5 text-[12px] text-text-dim">
                  {searchMode === "keyword_and_embed_and_llm"
                    ? t("personaSetup.filters.matchingDeep", {
                        model: modelShort || judgeModel || "LLM",
                      })
                    : searchMode === "keyword_and_embed"
                      ? t("personaSetup.filters.matchingSmart")
                      : t("personaSetup.filters.matchingKeyword")}
                </p>
              ) : null}

              {matchErrorMessage ? (
                <p className="mt-2.5 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
                  {t("personaSetup.filters.matchFailed", {
                    detail: matchErrorMessage,
                  })}
                </p>
              ) : null}
            </div>
          </div>
          </div>

          <div
            className={
              allowOverlayEdit
                ? "mx-3 mb-3 flex min-h-0 flex-1 flex-col sm:mx-4"
                : "flex min-h-0 flex-1 flex-col"
            }
          >
            <div
              className={
                allowOverlayEdit
                  ? "relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-outline/25 bg-surface/40"
                  : "flex min-h-0 flex-1 flex-col border-t border-outline/25"
              }
            >
              {allowOverlayEdit ? (
                <div className="relative z-[2] flex shrink-0 justify-end border-b border-outline/30 px-4 py-2">
                  {renderOverlayAddButton()}
                </div>
              ) : null}

          <div className="flex min-h-0 flex-1 flex-col md:flex-row">
            {renderDirectory()}
            <div className="custom-scrollbar min-h-0 min-w-0 flex-1 overflow-y-auto px-5 py-3">
          <>
          {suggestions.length > 0 ? (
            <div className="mb-4 rounded-lg border border-outline/30 bg-surface/30 px-3 py-2.5">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-[12px] text-text-variant">
                  {t("personaSetup.filters.suggestedAttributes", {
                    count: suggestions.length,
                  })}
                  <span className="ml-1.5 text-text-dim">
                    ·{" "}
                    {resultMode === "keyword_and_embed_and_llm"
                      ? t("personaSetup.filters.matchedDeep")
                      : resultMode === "keyword_and_embed"
                        ? t("personaSetup.filters.matchedSmart")
                        : t("personaSetup.filters.matchedKeyword")}
                  </span>
                </p>
                <button
                  type="button"
                  onClick={() => {
                    pendingRevealKey.current = "__bottom";
                    setDraft((prev) => applyAllSuggestions(prev, suggestions));
                  }}
                  className={`rounded-md px-2 py-1 text-[11px] text-primary hover:bg-primary/10 ${FOCUS_RING}`}
                >
                  {t("personaSetup.filters.selectAll")}
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.map((attr) => {
                  const active = isSuggestionSelected(activeFilters, attr);
                  const label = labels.dimLabel(
                    attr.dimensionId,
                    (attr.label || attr.dimensionId).replace(/_/g, " "),
                  );
                  return (
                    <button
                      key={suggestionKey(attr)}
                      type="button"
                      title={
                        attr.evidence
                          ? t("personaSetup.filters.evidence", {
                              value: attr.evidence,
                            })
                          : undefined
                      }
                      onClick={() => {
                        if (!active) {
                          pendingRevealKey.current = `${attr.dimensionId}:${attr.value}`;
                        }
                        setDraft((prev) =>
                          toggleSuggestionInFilters(prev, attr),
                        );
                      }}
                      className={`rounded-full px-2.5 py-1 text-[12px] ${FOCUS_RING} ${
                        active
                          ? "glass-tile glass-tile--active text-primary"
                          : "glass-tile glass-tile--hover text-text-variant"
                      }`}
                    >
                      <span className="text-text-dim">{label}</span>
                      <span className="mx-1 text-text-dim">·</span>
                      {attr.valueLabel ||
                        labels.valueLabel(attr.dimensionId, attr.value)}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          <div className="space-y-2">
            {showEmptyTree ? (
              <p className="rounded-lg border border-dashed border-outline/40 px-3 py-4 text-center text-[13px] text-text-dim">
                {t("personaSetup.filters.noAttributes", {
                  query: query.trim(),
                })}
              </p>
            ) : null}
            {visibleGroups.map((group) => {
              const groupOpen =
                expandedGroup === group.id || Boolean(normalizedQuery);
              const subgroups = group.subgroups ?? [];
              return (
                <div
                  id={`pf-group-${group.id}`}
                  key={group.id}
                  className="scroll-mt-2 rounded-lg border border-outline/30"
                >
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedGroup(
                        groupOpen && !normalizedQuery ? null : group.id,
                      )
                    }
                    className={`flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-[13px] font-medium ${FOCUS_RING}`}
                  >
                    <span>
                      {groupDisplayLabel(
                        group,
                        labels,
                        t("personaSetup.filters.overlayGroup"),
                      )}
                    </span>
                    <Sym
                      name={groupOpen ? "expand_less" : "expand_more"}
                      size={18}
                      className="text-text-dim"
                    />
                  </button>
                  {groupOpen ? (
                    <div className="space-y-2 border-t border-outline/20 px-2.5 py-2">
                      {subgroups.length > 0
                        ? subgroups.map((sub) => {
                            const subOpen =
                              expandedSubgroup === sub.id ||
                              Boolean(normalizedQuery);
                            return (
                              <div
                                id={`pf-sub-${sub.id}`}
                                key={sub.id}
                                className="scroll-mt-2 rounded-md border border-outline/20"
                              >
                                <button
                                  type="button"
                                  onClick={() =>
                                    setExpandedSubgroup(
                                      subOpen && !normalizedQuery
                                        ? null
                                        : sub.id,
                                    )
                                  }
                                  className={`flex w-full items-center justify-between gap-2 px-2.5 py-2 text-left text-[12px] text-text-variant ${FOCUS_RING}`}
                                >
                                  <span>
                                    {labels.taxonomyLabel(sub.id, sub.label)}
                                  </span>
                                  <Sym
                                    name={
                                      subOpen ? "expand_less" : "expand_more"
                                    }
                                    size={16}
                                    className="text-text-dim"
                                  />
                                </button>
                                {subOpen ? (
                                  <div className="space-y-1.5 border-t border-outline/15 px-2 py-2">
                                    {(sub.dimensions ?? []).map(
                                      renderDimension,
                                    )}
                                  </div>
                                ) : null}
                              </div>
                            );
                          })
                        : (group.dimensions ?? []).map(renderDimension)}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
          </>
            </div>
            {selectedPaneVisible ? renderSelected() : null}
          </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-stretch gap-1.5 border-t border-outline/40 bg-surface/40 px-5 py-3 sm:flex-row sm:items-center sm:justify-end">
              <div className="flex shrink-0 items-center justify-end gap-2 sm:ml-auto">
              <button
                type="button"
                onClick={onClose}
                className={`rounded-md border border-outline px-3 py-2 text-[14px] text-text-variant ${FOCUS_RING}`}
              >
                {t("personaSetup.common.cancel")}
              </button>
              <button
                type="button"
                onClick={() => {
                  if (allowOverlayEdit) {
                    onConfirm(
                      draft,
                      showMarginals ? draftMarginals : undefined,
                      draftOverlay,
                    );
                  } else {
                    onConfirm(
                      draft,
                      showMarginals ? draftMarginals : undefined,
                    );
                  }
                  onClose();
                }}
                className={`rounded-md bg-primary px-4 py-2 text-[14px] font-medium text-on-primary ${FOCUS_RING}`}
              >
                {t(FILTER_APPLY_KEYS[overlayMode(allowOverlayEdit)])}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )}
      {allowOverlayEdit ? (
        <OverlayDimensionDialog
          open={overlayDialogOpen}
          takenIds={
            new Set([...catalogDimIds, ...draftOverlay.map((dim) => dim.id)])
          }
          onClose={() => setOverlayDialogOpen(false)}
          onAdd={addOverlayDimensions}
        />
      ) : null}
    </>
  );
}
