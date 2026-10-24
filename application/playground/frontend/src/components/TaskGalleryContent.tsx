/**
 * TaskGalleryContent: cross-type task catalog grid (Task Gallery page).
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  chatbotEvalTaskCards,
  osAppTaskCards,
  surveyHarborTaskCards,
  webEvalTaskCards,
} from "./cockpit/setup/cockpitTaskCards";
import { TaskDetailModal } from "./cockpit/setup/TaskDetailModal";
import type { TaskCardModel } from "./cockpit/setup/TaskSelectionRail";
import { taskAvailabilityPresentation } from "./cockpit/setup/taskAvailability";
import { taskCardIcon, taskMetaTypeIcon } from "./cockpit/setup/taskCardIcons";
import {
  CHIP_TEXT_CLASS,
  formatChipLabel,
  taskCardTagKey,
  taskCardTagLabel,
  taskCardTags,
  taskCardTagSearchText,
} from "./cockpit/setup/taskCardLabels";
import {
  ToneChip,
  transportChipTone,
  type ToneChipTone,
} from "./cockpit/setup/ToneChip";
import type { PlaygroundTaskType } from "./cockpit/TaskTypeSwitch";
import { FOCUS_RING, Sym } from "./cockpit/cockpitShared";
import { StudioGlassPanel } from "./studio/StudioShell";
import { useI18n, type I18nContextValue } from "@/i18n/I18nProvider";
import { taskTransportLabel } from "./cockpit/setup/taskCardPresentation";
import { api, listChatbotEvalTasks, listOsAppEvalTasks, listSurveyHarborTasks, listWebEvalTasks } from "@/lib/api";
import type { ChatbotEvalTask, ExperimentTaskSummary } from "@/lib/types";
import { AXIS_META, designLabel } from "./experiments/experimentShared";

type KindFilter = "all" | "playground" | "experiment";
type TypeFilter = "all" | PlaygroundTaskType;

const KIND_FILTERS: ReadonlyArray<KindFilter> = ["all", "playground", "experiment"];
const TYPE_FILTERS: ReadonlyArray<TypeFilter> = [
  "all",
  "survey",
  "chatbot",
  "web",
  "os-app",
];

type PlaygroundGalleryItem = { kind: "playground"; card: TaskCardModel };
type ExperimentGalleryItem = { kind: "experiment"; task: ExperimentTaskSummary };
type GalleryItem = PlaygroundGalleryItem | ExperimentGalleryItem;

function kindFilterLabel(value: KindFilter, t: I18nContextValue["t"]): string {
  switch (value) {
    case "all":
      return t("catalog.taskGallery.filter.all");
    case "playground":
      return t("catalog.taskGallery.filter.playground");
    case "experiment":
      return t("catalog.taskGallery.filter.experiments");
    default:
      return value;
  }
}

function typeFilterLabel(value: TypeFilter, t: I18nContextValue["t"]): string {
  switch (value) {
    case "all":
      return t("catalog.taskGallery.filter.all");
    case "survey":
      return t("catalog.taskGallery.filter.survey");
    case "chatbot":
      return t("catalog.taskGallery.filter.chatbot");
    case "web":
      return t("catalog.taskGallery.filter.web");
    case "os-app":
      return t("catalog.taskGallery.filter.osApp");
    default:
      return value;
  }
}

function appTypeChipLabel(taskType: PlaygroundTaskType, t: I18nContextValue["t"]): string {
  switch (taskType) {
    case "survey":
      return t("catalog.taskGallery.filter.survey");
    case "chatbot":
      return t("catalog.taskGallery.filter.chatbot");
    case "web":
      return t("catalog.taskGallery.filter.web");
    case "os-app":
      return t("catalog.taskGallery.filter.osApp");
    default:
      return formatChipLabel(taskType);
  }
}

function designChipLabel(designType: string | undefined, t: I18nContextValue["t"]): string {
  switch (designType) {
    case "full_factorial":
      return t("catalog.taskGallery.design.fullFactorial");
    case "fractional":
      return t("catalog.taskGallery.design.fractional");
    case "put":
      return t("catalog.taskGallery.design.personaContrast");
    default:
      // ``ab_n`` stays "A/B/n" (design notation, untranslated); unknowns are humanized.
      return designLabel(designType);
  }
}

function normalizeExperimentAppType(appType: string | undefined): PlaygroundTaskType | null {
  const value = (appType ?? "").toLowerCase().replace(/_/g, "-");
  if (value === "survey" || value === "chatbot" || value === "web" || value === "os-app") {
    return value;
  }
  return null;
}

function experimentSearchHaystack(task: ExperimentTaskSummary): string {
  return [
    task.task,
    task.name,
    task.title ?? "",
    task.hypothesis ?? "",
    task.appType ?? "",
    task.domain ?? "",
    task.difficulty ?? "",
    task.axis ?? "",
    task.putDimension ?? "",
    task.designType ?? "",
  ]
    .join(" ")
    .toLowerCase();
}

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

function taskSearchHaystack(card: TaskCardModel): string {
  return [
    card.id,
    card.title,
    card.subtitle ?? "",
    card.taskPath,
    card.domain ?? "",
    card.difficulty ?? "",
    card.metaType ?? "",
    card.platform ?? "",
    card.os ?? "",
    ...(card.searchTags ?? []),
    ...(card.tags?.map(taskCardTagSearchText) ?? []),
  ]
    .join(" ")
    .toLowerCase();
}

export interface TaskGalleryContentProps {
  onOpenInPlayground: (taskType: PlaygroundTaskType, taskId: string) => void;
  onOpenExperimentTask: (taskPath: string) => void;
  autoFocusSearch?: boolean;
}

export function TaskGalleryContent({
  onOpenInPlayground,
  onOpenExperimentTask,
  autoFocusSearch = false,
}: TaskGalleryContentProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [detailCard, setDetailCard] = useState<TaskCardModel | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debouncedQuery = useDebounced(query.trim(), 220);

  useEffect(() => {
    if (!autoFocusSearch) return;
    const id = window.setTimeout(() => inputRef.current?.focus(), 40);
    return () => window.clearTimeout(id);
  }, [autoFocusSearch]);

  const surveyQuery = useQuery({
    queryKey: ["survey-eval-harbor-tasks"],
    queryFn: listSurveyHarborTasks,
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
  const chatbotQuery = useQuery({
    queryKey: ["chatbot-eval-tasks"],
    queryFn: listChatbotEvalTasks,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
  const webQuery = useQuery({
    queryKey: ["web-eval-tasks"],
    queryFn: listWebEvalTasks,
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
  const osAppQuery = useQuery({
    queryKey: ["os-app-eval-tasks"],
    queryFn: listOsAppEvalTasks,
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
  const experimentQuery = useQuery({
    queryKey: ["experiment-tasks"],
    queryFn: api.listExperimentTasks,
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  const allItems = useMemo<GalleryItem[]>(() => {
    const surveyTasks = surveyQuery.data?.tasks ?? [];
    const chatbotTasks: ChatbotEvalTask[] = chatbotQuery.data?.tasks ?? [];
    const webTasks = webQuery.data?.tasks ?? [];
    const osAppTasks = osAppQuery.data?.tasks ?? [];
    const playground: PlaygroundGalleryItem[] = [
      ...surveyHarborTaskCards(surveyTasks),
      ...chatbotEvalTaskCards(chatbotTasks),
      ...webEvalTaskCards(webTasks),
      ...osAppTaskCards(osAppTasks),
    ].map((card) => ({ kind: "playground", card }));
    const experiments: ExperimentGalleryItem[] = (experimentQuery.data?.tasks ?? []).map(
      (task) => ({ kind: "experiment", task }),
    );
    return [...playground, ...experiments];
  }, [
    chatbotQuery.data?.tasks,
    experimentQuery.data?.tasks,
    osAppQuery.data?.tasks,
    surveyQuery.data?.tasks,
    webQuery.data?.tasks,
  ]);

  const filtered = useMemo(() => {
    const q = debouncedQuery.toLowerCase();
    return allItems.filter((item) => {
      if (kindFilter !== "all" && item.kind !== kindFilter) return false;
      if (typeFilter !== "all") {
        const appType =
          item.kind === "experiment"
            ? normalizeExperimentAppType(item.task.appType)
            : item.card.taskType;
        if (appType !== typeFilter) return false;
      }
      if (!q) return true;
      return item.kind === "experiment"
        ? experimentSearchHaystack(item.task).includes(q)
        : taskSearchHaystack(item.card).includes(q);
    });
  }, [allItems, debouncedQuery, kindFilter, typeFilter]);

  const loading =
    (surveyQuery.isLoading ||
      chatbotQuery.isLoading ||
      webQuery.isLoading ||
      osAppQuery.isLoading ||
      experimentQuery.isLoading) &&
    allItems.length === 0;
  const allFailed =
    surveyQuery.isError &&
    chatbotQuery.isError &&
    webQuery.isError &&
    osAppQuery.isError &&
    experimentQuery.isError &&
    allItems.length === 0;

  function handleOpen(card: TaskCardModel) {
    onOpenInPlayground(card.taskType, card.id);
  }

  const filtersActive = kindFilter !== "all" || typeFilter !== "all" || Boolean(debouncedQuery);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <StudioGlassPanel className="mb-4 shrink-0 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="glass-tile flex h-9 min-w-0 flex-1 basis-56 items-center rounded-lg transition-colors focus-within:bg-surface-high/50">
            <Sym
              name="search"
              size={16}
              className="ml-3 flex-none text-text-dim"
            />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("catalog.taskGallery.searchPlaceholder")}
              aria-label={t("catalog.taskGallery.searchTasks")}
              className="h-full w-full min-w-0 bg-transparent px-3 text-[14px] text-text-main outline-none placeholder:text-text-variant"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label={t("catalog.taskGallery.clearSearch")}
                className={`mr-2 flex-none rounded p-1 text-text-dim transition-colors hover:bg-surface-high hover:text-text-main ${FOCUS_RING}`}
              >
                <Sym name="close" size={16} />
              </button>
            )}
          </div>

          <div className="flex shrink-0 items-baseline gap-1.5 pl-1">
            <span className="hud text-[11px] text-text-dim">
              {t("catalog.taskGallery.tasks")}
            </span>
            <span className="font-mono text-[15px] font-bold text-primary">
              {loading
                ? t("catalog.taskGallery.loading")
                : allItems.length.toLocaleString()}
            </span>
          </div>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label={t("catalog.taskGallery.filterBySource")}
          >
            <span className="hud pr-0.5 text-[10px] tracking-wide text-text-dim">
              {t("catalog.taskGallery.source")}
            </span>
            {KIND_FILTERS.map((value) => (
              <FilterChip
                key={value}
                label={kindFilterLabel(value, t)}
                active={kindFilter === value}
                onClick={() => setKindFilter(value)}
              />
            ))}
          </div>
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label={t("catalog.taskGallery.filterByTaskType")}
          >
            <span className="hud pr-0.5 text-[10px] tracking-wide text-text-dim">
              {t("catalog.taskGallery.appType")}
            </span>
            {TYPE_FILTERS.map((value) => (
              <FilterChip
                key={value}
                label={typeFilterLabel(value, t)}
                active={typeFilter === value}
                onClick={() => setTypeFilter(value)}
              />
            ))}
          </div>
        </div>

        {filtersActive && (
          <p className="mt-2 text-[13px] text-text-variant">
            {t("catalog.taskGallery.showing", {
              shown: filtered.length,
              total: allItems.length,
            })}
          </p>
        )}
      </StudioGlassPanel>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-auto">
      {loading ? (
        <CatalogSkeleton />
      ) : allFailed ? (
        <CatalogError
          onRetry={() => {
            void surveyQuery.refetch();
            void chatbotQuery.refetch();
            void webQuery.refetch();
            void osAppQuery.refetch();
            void experimentQuery.refetch();
          }}
        />
      ) : filtered.length === 0 ? (
        <CatalogEmpty
          query={debouncedQuery}
          hasTypeFilter={kindFilter !== "all" || typeFilter !== "all"}
        />
      ) : (
        <div className="grid grid-cols-1 items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((item, i) => (
            <div
              key={
                item.kind === "experiment"
                  ? `experiment:${item.task.task}`
                  : `${item.card.taskType}:${item.card.id}`
              }
              className="rise-in h-full"
              style={{ animationDelay: `${Math.min(i, 8) * 25}ms` }}
            >
              {item.kind === "experiment" ? (
                <GalleryExperimentCard
                  task={item.task}
                  onOpen={() => onOpenExperimentTask(item.task.task)}
                />
              ) : (
                <GalleryTaskCard
                  card={item.card}
                  onOpenDetail={() => setDetailCard(item.card)}
                  onOpenInPlayground={() => handleOpen(item.card)}
                />
              )}
            </div>
          ))}
        </div>
      )}
      </div>

      <TaskDetailModal
        open={Boolean(detailCard)}
        card={detailCard}
        onClose={() => setDetailCard(null)}
        primaryAction={
          detailCard
            ? {
                label: t("catalog.taskGallery.openPlayground"),
                onClick: () => handleOpen(detailCard),
              }
            : undefined
        }
      />
    </div>
  );
}

function GalleryTaskCard({
  card,
  onOpenDetail,
  onOpenInPlayground,
}: {
  card: TaskCardModel;
  onOpenDetail: () => void;
  onOpenInPlayground: () => void;
}) {
  const { t } = useI18n();
  const unavailable = card.available === false;
  const availability = taskAvailabilityPresentation(card.availabilityStatus, t);
  return (
    <div
      className={`flex h-full flex-col rounded-xl border transition ${
        unavailable
          ? "border-outline/35 bg-surface/20 opacity-80"
          : "border-outline/40 bg-surface/30 hover:border-primary/30"
      }`}
    >
      <button
        type="button"
        onClick={onOpenDetail}
        className={`flex min-h-0 flex-1 items-start gap-3 p-4 text-left ${FOCUS_RING}`}
      >
        <GalleryGlyph
          appIcon={taskCardIcon(card.taskType, card)}
          source="playground"
        />
        <div className="min-w-0 flex-1">
          <p className="font-display text-[14px] font-semibold leading-tight text-text-main">
            {card.title}
          </p>
          {card.subtitle && (
            <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-text-dim">
              {card.subtitle}
            </p>
          )}
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <ToneChip tone="primary" className={CHIP_TEXT_CLASS}>
              {appTypeChipLabel(card.taskType, t)}
            </ToneChip>
            {card.transport && (
              <ToneChip
                tone={transportChipTone(card.transport)}
                className={CHIP_TEXT_CLASS}
              >
                {taskTransportLabel(card.transport, t)}
              </ToneChip>
            )}
            {(
              card.tags ??
              card.tagLabels?.map((label) => ({
                label,
                tone: "neutral" as ToneChipTone,
              })) ??
              []
            )
              .slice(0, 4)
              .map((tag) => (
                <ToneChip
                  key={taskCardTagKey(tag)}
                  tone={tag.tone}
                  className={CHIP_TEXT_CLASS}
                >
                  {taskCardTagLabel(tag, t)}
                </ToneChip>
              ))}
            {availability && (
              <ToneChip
                key={`availability:${card.availabilityStatus}`}
                tone={availability.tone}
                showDot
                className={CHIP_TEXT_CLASS}
              >
                {availability.label}
              </ToneChip>
            )}
          </div>
        </div>
      </button>
      <CardActionRow
        onDetails={onOpenDetail}
        onOpen={onOpenInPlayground}
        openLabel={t("catalog.taskGallery.openPlayground")}
        openIcon="play_arrow"
      />
    </div>
  );
}

function GalleryExperimentCard({
  task,
  onOpen,
}: {
  task: ExperimentTaskSummary;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const axis = task.axis === "put" ? "put" : "sut";
  const appType = normalizeExperimentAppType(task.appType);
  return (
    <div className="flex h-full flex-col rounded-xl border border-outline/40 bg-surface/30 transition hover:border-primary/30">
      <button
        type="button"
        onClick={onOpen}
        className={`flex min-h-0 flex-1 items-start gap-3 p-4 text-left ${FOCUS_RING}`}
      >
        <GalleryGlyph
          appIcon={taskMetaTypeIcon(appType ?? undefined)}
          source="experiment"
        />
        <div className="min-w-0 flex-1">
          <p className="font-display text-[14px] font-semibold leading-tight text-text-main">
            {task.name}
          </p>
          {task.hypothesis ? (
            <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-text-dim">
              {task.hypothesis}
            </p>
          ) : null}
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {appType ? (
              <ToneChip tone="primary" className={CHIP_TEXT_CLASS}>
                {appTypeChipLabel(appType, t)}
              </ToneChip>
            ) : null}
            {taskCardTags({
              taskPath: task.task,
              domain: task.domain ?? undefined,
              difficulty: task.difficulty ?? undefined,
            }).map((tag) => (
              <ToneChip
                key={taskCardTagKey(tag)}
                tone={tag.tone}
                className={CHIP_TEXT_CLASS}
              >
                {taskCardTagLabel(tag, t)}
              </ToneChip>
            ))}
          </div>
        </div>
      </button>
      <CardActionRow
        onDetails={onOpen}
        onOpen={onOpen}
        openLabel={t("catalog.taskGallery.openExperiments")}
        openIcon="science"
        chips={
          <>
            <ToneChip
              tone={axis === "put" ? "secondary" : "primary"}
              className={CHIP_TEXT_CLASS}
            >
              {AXIS_META[axis].code}
            </ToneChip>
            <ToneChip tone="neutral" className={CHIP_TEXT_CLASS}>
              {designChipLabel(task.designType, t)}
            </ToneChip>
          </>
        }
      />
    </div>
  );
}

/** Two equal icons: app type, then Playground vs Experiments. */
function GalleryGlyph({
  appIcon,
  source,
}: {
  appIcon: string;
  source: "playground" | "experiment";
}) {
  const experiment = source === "experiment";
  return (
    <div className="flex shrink-0 flex-col items-center gap-1.5">
      <div className="grid h-10 w-10 place-items-center rounded-lg border border-outline/40 bg-surface-high/60">
        <Sym name={appIcon} size={20} className="text-text-variant" />
      </div>
      <div
        className={`grid h-10 w-10 place-items-center rounded-lg border ${
          experiment
            ? "border-primary/35 bg-primary/12 text-primary"
            : "border-secondary/35 bg-secondary/12 text-secondary"
        }`}
      >
        <Sym name={experiment ? "science" : "play_arrow"} size={20} />
      </div>
    </div>
  );
}

function CardActionRow({
  onDetails,
  onOpen,
  openLabel,
  openIcon,
  chips,
}: {
  onDetails: () => void;
  onOpen: () => void;
  openLabel: string;
  openIcon: string;
  chips?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col gap-2 border-t border-outline/25 px-3 py-2.5">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={onDetails}
          className={`inline-flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-[12px] font-medium text-text-variant hover:bg-surface-high hover:text-text-main ${FOCUS_RING}`}
        >
          <Sym name="info" size={14} />
          {t("catalog.taskGallery.details")}
        </button>
        {chips ? (
          <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-1.5">
            {chips}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onOpen}
        className={`glass-tile glass-tile--hover inline-flex min-h-8 w-full items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-semibold text-primary ${FOCUS_RING}`}
      >
        <Sym name={openIcon} size={15} className="shrink-0" />
        <span>{openLabel}</span>
      </button>
    </div>
  );
}

function FilterChip({
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
      className={`inline-flex h-8 items-center rounded-md px-3 text-[13px] font-medium transition-colors ${FOCUS_RING} ${
        active
          ? "bg-primary text-on-primary"
          : "glass-tile glass-tile--hover text-text-variant hover:text-text-main"
      }`}
    >
      {label}
    </button>
  );
}

function CatalogSkeleton() {
  return (
    <div
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      aria-hidden
    >
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="glass-panel rounded-xl p-4">
          <div className="mb-3 flex items-start justify-between">
            <div className="h-10 w-10 animate-rb-pulse rounded bg-surface-high" />
            <div className="h-3.5 w-14 animate-rb-pulse rounded bg-surface-high" />
          </div>
          <div className="h-3.5 w-2/3 animate-rb-pulse rounded bg-surface-high" />
          <div className="mt-2 h-2.5 w-1/2 animate-rb-pulse rounded bg-surface-high" />
        </div>
      ))}
    </div>
  );
}

function CatalogEmpty({
  query,
  hasTypeFilter,
}: {
  query: string;
  hasTypeFilter: boolean;
}) {
  const { t } = useI18n();

  return (
    <div className="glass-panel rise-in flex flex-col items-center rounded-xl px-4 py-16 text-center">
      <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-lg border border-dashed border-outline/50 bg-surface/50">
        <Sym name="search_off" size={26} className="text-text-dim" />
      </div>
      <p className="font-display text-[15px] font-semibold text-text-main">
        {query || hasTypeFilter
          ? t("catalog.taskGallery.noMatches")
          : t("catalog.taskGallery.noTasksYet")}
      </p>
      <p className="mt-1 max-w-[320px] text-[14px] leading-snug text-text-variant">
        {query
          ? t("catalog.taskGallery.nothingMatches", { query })
          : hasTypeFilter
            ? t("catalog.taskGallery.noTasksInType")
            : t("catalog.taskGallery.emptyDescription")}
      </p>
    </div>
  );
}

function CatalogError({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();

  return (
    <div className="glass-panel rise-in mx-auto max-w-md rounded-xl border-l-4 border-l-danger px-4 py-6 text-center">
      <Sym name="error" size={24} className="mx-auto mb-2 text-danger" />
      <p className="font-display text-[15px] font-semibold text-text-main">
        {t("catalog.taskGallery.loadFailed")}
      </p>
      <p className="mx-auto mt-1 max-w-[300px] text-[14px] leading-snug text-text-variant">
        {t("catalog.taskGallery.loadFailedDescription")}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className={`mt-3 inline-flex items-center gap-1.5 rounded-md border border-danger/40 bg-danger/10 px-3 py-1.5 text-[13px] font-medium text-danger ${FOCUS_RING}`}
      >
        <Sym name="refresh" size={15} />
        {t("catalog.taskGallery.tryAgain")}
      </button>
    </div>
  );
}
