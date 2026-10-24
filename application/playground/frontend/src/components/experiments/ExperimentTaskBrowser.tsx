import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  ExperimentAxis,
  ExperimentDesignType,
  ExperimentTaskListResponse,
  ExperimentTaskSummary,
} from "@/lib/types";
import { useI18n } from "@/i18n/I18nProvider";
import { FOCUS_RING, Sym, humanizeToken } from "../cockpit/cockpitShared";
import { StudioGlassPanel } from "../studio/StudioShell";
import { AXIS_META, CARD_CLASS, MetaChip, designLabel, errMessage } from "./experimentShared";
import { formatChipLabel } from "../cockpit/setup/taskCardLabels";
export interface ExperimentTaskBrowserProps {
  onOpenTask: (taskPath: string) => void;
}

type AxisFilter = "all" | ExperimentAxis;
type AppFilter = "all" | "survey" | "chatbot" | "web" | "os-app";
type DesignFilter = "all" | ExperimentDesignType;

const AXIS_FILTERS: AxisFilter[] = ["all", "sut", "put"];
const APP_FILTERS: AppFilter[] = ["all", "survey", "chatbot", "web", "os-app"];
const DESIGN_FILTERS: DesignFilter[] = ["all", "ab_n", "full_factorial", "fractional"];

function normalizeAppType(appType: string | undefined): AppFilter | null {
  const value = (appType ?? "").toLowerCase().replace(/_/g, "-");
  if (value === "survey" || value === "chatbot" || value === "web" || value === "os-app") {
    return value;
  }
  return null;
}

function appTypeLabel(
  value: AppFilter,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (value === "all") return t("experiments.taskBrowser.all");
  if (value === "chatbot") return t("experiments.list.filter.app.chatbot");
  if (value === "survey") return t("experiments.list.filter.app.survey");
  if (value === "web") return t("experiments.list.filter.app.web");
  if (value === "os-app") return t("experiments.list.filter.app.osApp");
  return formatChipLabel(value);
}

function normalizeDesign(type: string | undefined): ExperimentDesignType | null {
  if (type === "ab_n" || type === "full_factorial" || type === "fractional") {
    return type;
  }
  return null;
}

/**
 * Gallery-style browse: filter by axis, app type, and design, then pick a task.
 * You do not author a task here.
 */
export function ExperimentTaskBrowser({ onOpenTask }: ExperimentTaskBrowserProps) {
  const { t, rich } = useI18n();
  const [axisFilter, setAxisFilter] = useState<AxisFilter>("all");
  const [appFilter, setAppFilter] = useState<AppFilter>("all");
  const [designFilter, setDesignFilter] = useState<DesignFilter>("all");

  const tasksQuery = useQuery<ExperimentTaskListResponse>({
    queryKey: ["experiment-tasks"],
    queryFn: api.listExperimentTasks,
  });

  const allTasks = tasksQuery.data?.tasks ?? [];
  const filtered = useMemo(() => {
    return allTasks.filter((task) => {
      const axis: ExperimentAxis = task.axis === "put" ? "put" : "sut";
      if (axisFilter !== "all" && axis !== axisFilter) return false;
      if (appFilter !== "all" && normalizeAppType(task.appType) !== appFilter) return false;
      if (designFilter !== "all" && normalizeDesign(task.designType) !== designFilter) {
        return false;
      }
      return true;
    });
  }, [allTasks, axisFilter, appFilter, designFilter]);

  if (tasksQuery.isLoading) {
    return <p className="text-[13px] text-text-dim">{t("experiments.taskBrowser.loading")}</p>;
  }
  if (tasksQuery.isError) {
    return (
      <p className="rounded-md bg-danger/10 p-3 text-[13px] text-danger" role="alert">
        {errMessage(tasksQuery.error)}
      </p>
    );
  }

  if (allTasks.length === 0) {
    return (
      <StudioGlassPanel className="px-6 py-14 text-center">
        <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-md glass-tile">
          <Sym name="science" size={26} className="text-text-dim" />
        </div>
        <h2 className="font-display text-[15px] font-semibold text-text-main">
          {t("experiments.taskBrowser.emptyTitle")}
        </h2>
        <p className="mx-auto mt-2 max-w-md text-[13.5px] leading-relaxed text-text-variant">
          {rich("experiments.taskBrowser.emptyBody", {
            code: (chunks) => <span className="font-mono">{chunks}</span>,
            path: (chunks) => <span className="font-mono">{chunks}</span>,
          })}
        </p>
      </StudioGlassPanel>
    );
  }

  const axisHint = axisFilter === "all" ? null : AXIS_META[axisFilter];

  return (
    <div>
      <StudioGlassPanel className="mb-4 p-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t("experiments.taskBrowser.filterByAxis")}>
            <span className="hud pr-0.5 text-[10px] tracking-wide text-text-dim">{t("experiments.taskBrowser.axisLabel")}</span>
            {AXIS_FILTERS.map((value) => (
              <FilterChip
                key={value}
                label={value === "all" ? t("experiments.taskBrowser.all") : AXIS_META[value].code}
                active={axisFilter === value}
                onClick={() => setAxisFilter(value)}
              />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t("experiments.taskBrowser.filterByAppType")}>
            <span className="hud pr-0.5 text-[10px] tracking-wide text-text-dim">{t("experiments.taskBrowser.appTypeLabel")}</span>
            {APP_FILTERS.map((value) => (
              <FilterChip
                key={value}
                label={appTypeLabel(value, t)}
                active={appFilter === value}
                onClick={() => setAppFilter(value)}
              />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t("experiments.taskBrowser.filterByDesign")}>
            <span className="hud pr-0.5 text-[10px] tracking-wide text-text-dim">{t("experiments.taskBrowser.designLabel")}</span>
            {DESIGN_FILTERS.map((value) => (
              <FilterChip
                key={value}
                label={value === "all" ? t("experiments.taskBrowser.all") : designLabel(value, t)}
                active={designFilter === value}
                onClick={() => setDesignFilter(value)}
              />
            ))}
          </div>
          <div className="ml-auto flex shrink-0 items-baseline gap-1">
            <span className="font-mono text-[15px] font-bold text-primary">{filtered.length}</span>
            <span className="hud text-[11px] text-text-dim">{t("experiments.taskBrowser.tasksLabel")}</span>
          </div>
        </div>
        {axisHint ? (
          <p className="mt-2 text-[12px] text-text-dim">{axisHint.blurb}</p>
        ) : null}
      </StudioGlassPanel>

      {filtered.length === 0 ? (
        <StudioGlassPanel className="px-4 py-10 text-center text-[13px] text-text-dim">
          {t("experiments.taskBrowser.noMatches")}
        </StudioGlassPanel>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {filtered.map((task) => (
            <TaskCard key={task.task} task={task} onOpen={onOpenTask} />
          ))}
        </div>
      )}
    </div>
  );
}

function TaskCard({
  task,
  onOpen,
}: {
  task: ExperimentTaskSummary;
  onOpen: (taskPath: string) => void;
}) {
  const { t } = useI18n();
  const axis: ExperimentAxis = task.axis === "put" ? "put" : "sut";
  const appType = normalizeAppType(task.appType);
  const accent = axis === "put" ? "hover:border-secondary/40" : "hover:border-primary/40";
  const factors = cardFactorLabels(task);
  const primary = task.primaryMetrics ?? [];
  return (
    <button
      type="button"
      onClick={() => onOpen(task.task)}
      className={`group flex flex-col ${CARD_CLASS} ${accent} p-4 text-left ${FOCUS_RING}`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <span className="font-display text-[15px] font-semibold leading-snug text-text-main">
          {task.name}
        </span>
        <MetaChip
          tone={axis === "put" ? "secondary" : "primary"}
          className="shrink-0 font-bold"
        >
          {AXIS_META[axis].code}
        </MetaChip>
      </div>
      {task.hypothesis ? (
        <p className="mb-2 line-clamp-3 text-[13px] leading-relaxed text-text-variant">
          {task.hypothesis}
        </p>
      ) : (
        <p className="mb-2 text-[13px] italic text-text-dim">{t("experiments.taskBrowser.noHypothesis")}</p>
      )}
      {factors.length > 0 || primary.length > 0 ? (
        <div className="mb-3 space-y-0.5 text-[12px] leading-snug text-text-dim">
          {factors.length > 0 ? (
            <p className="line-clamp-2">
              <span className="font-medium text-text-variant">{t("experiments.taskBrowser.factors")}{" · "}</span>
              {factors.join(" · ")}
            </p>
          ) : null}
          {primary.length > 0 ? (
            <p className="line-clamp-1">
              <span className="font-medium text-text-variant">{t("experiments.taskBrowser.primary")}{" · "}</span>
              {primary.map((key) => humanizeToken(key)).join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}
      <div className="mt-auto flex flex-wrap items-center gap-1.5">
        {appType ? (
          <MetaChip tone="primary">
            {appTypeLabel(appType as AppFilter, t)}
          </MetaChip>
        ) : null}
        {task.domain ? <MetaChip>{formatChipLabel(task.domain)}</MetaChip> : null}
        {task.difficulty ? <MetaChip>{formatChipLabel(task.difficulty)}</MetaChip> : null}
        <MetaChip>{designLabel(task.designType, t)}</MetaChip>
        <span className="ml-auto inline-flex items-center gap-0.5 text-[11px] text-primary opacity-0 transition group-hover:opacity-100">
          {t("experiments.taskBrowser.view")} <Sym name="arrow_forward" size={14} />
        </span>
      </div>
    </button>
  );
}

/** Factor names only — PUT dimension is a factor, not a stand-in for design type. */
function cardFactorLabels(task: ExperimentTaskSummary): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  const push = (raw: string | null | undefined) => {
    const label = (raw ?? "").trim();
    if (!label) return;
    const key = label.toLowerCase().replace(/_/g, " ");
    if (seen.has(key)) return;
    seen.add(key);
    out.push(label.includes("_") || label === label.toLowerCase() ? humanizeToken(label) : label);
  };
  if (task.axis === "put") {
    push(task.putDimension);
    return out;
  }
  for (const label of task.factorLabels ?? []) push(label);
  return out;
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
