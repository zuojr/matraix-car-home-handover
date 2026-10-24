import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "@/i18n/I18nProvider";
import type { MessageKey } from "@/i18n/types";
import { ApiError, api } from "@/lib/api";
import type { ExperimentListResponse, ExperimentSummary } from "@/lib/types";
import { FOCUS_RING, Sym } from "../cockpit/cockpitShared";
import { StudioGlassPanel } from "../studio/StudioShell";
import { AppTypeTag, fmtRunDate } from "../runsShared";
import { AxisBadge, StatusChip, designLabel } from "./experimentShared";

export interface ExperimentsListProps {
  onOpen: (id: string) => void;
  onNew: () => void;
}

type AppTypeFilter = "all" | "chatbot" | "survey" | "web" | "os-app";
type StatusFilter = "all" | "running" | "complete" | "failed";
type AxisFilter = "all" | "sut" | "put";
type DesignFilter = "all" | "ab_n" | "full_factorial" | "fractional";

const APP_TYPE_LABELS = {
  chatbot: "experiments.list.filter.app.chatbot",
  survey: "experiments.list.filter.app.survey",
  web: "experiments.list.filter.app.web",
  "os-app": "experiments.list.filter.app.osApp",
} as const satisfies Record<string, MessageKey>;

const STATUS_LABELS = {
  running: "experiments.list.filter.status.running",
  complete: "experiments.list.filter.status.complete",
  failed: "experiments.list.filter.status.failed",
} as const satisfies Record<string, MessageKey>;

const AXIS_LABELS = {
  sut: "experiments.list.filter.axis.sut",
  put: "experiments.list.filter.axis.put",
} as const satisfies Record<string, MessageKey>;

const DESIGN_LABELS = {
  ab_n: "experiments.list.filter.design.abN",
  full_factorial: "experiments.list.filter.design.factorial",
  fractional: "experiments.list.filter.design.fractional",
} as const satisfies Record<string, MessageKey>;

const APP_TYPE_OPTIONS = Object.keys(APP_TYPE_LABELS) as Array<keyof typeof APP_TYPE_LABELS>;
const STATUS_OPTIONS = Object.keys(STATUS_LABELS) as Array<keyof typeof STATUS_LABELS>;
const AXIS_OPTIONS = Object.keys(AXIS_LABELS) as Array<keyof typeof AXIS_LABELS>;
const DESIGN_OPTIONS = Object.keys(DESIGN_LABELS) as Array<keyof typeof DESIGN_LABELS>;

/** Identity stays readable; the wrapper scrolls horizontally on narrow widths. */
const EXP_GRID =
  "grid min-w-[56rem] grid-cols-[minmax(14rem,1.6fr)_5rem_3.5rem_5.5rem_4.5rem_3.75rem_4.25rem_5.75rem_minmax(5.25rem,6rem)_2.25rem] items-center gap-x-3";

function normalizeAppType(exp: ExperimentSummary): string {
  const explicit = (exp.appType ?? "").toString().toLowerCase();
  if (explicit) return explicit;
  const hay = `${exp.task} ${exp.name ?? ""}`.toLowerCase();
  if (hay.includes("survey")) return "survey";
  if (hay.includes("web")) return "web";
  if (hay.includes("os-app") || hay.includes("computer-use") || hay.includes("appworld"))
    return "os-app";
  return "chatbot";
}

function normalizeAxis(exp: ExperimentSummary): AxisFilter {
  return exp.axis === "put" ? "put" : "sut";
}

function normalizeDesign(exp: ExperimentSummary): DesignFilter | "all" {
  const t = (exp.designType ?? "").toLowerCase();
  if (t === "ab_n" || t === "full_factorial" || t === "fractional") return t;
  return "all";
}

function statusBucket(status?: string): StatusFilter {
  const s = (status ?? "").toLowerCase();
  if (s === "complete" || s === "partial") return "complete";
  if (s === "failed" || s === "error") return "failed";
  if (s === "running" || s === "launching" || s === "pending") return "running";
  return "running";
}

function shortDesign(type: string | null | undefined, t: ReturnType<typeof useI18n>["t"]): string {
  if (!type) return "—";
  return designLabel(type, t);
}

function sortExperiments(items: ExperimentSummary[]): ExperimentSummary[] {
  return [...items].sort((a, b) => {
    const ta = Date.parse(a.createdAt ?? "") || 0;
    const tb = Date.parse(b.createdAt ?? "") || 0;
    return tb - ta;
  });
}

export function ExperimentsList({ onOpen, onNew }: ExperimentsListProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [appTypeFilter, setAppTypeFilter] = useState<AppTypeFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [axisFilter, setAxisFilter] = useState<AxisFilter>("all");
  const [designFilter, setDesignFilter] = useState<DesignFilter>("all");
  const [openHeader, setOpenHeader] = useState<string | null>(null);
  const experimentsQuery = useQuery<ExperimentListResponse>({
    queryKey: ["experiments"],
    queryFn: api.listExperiments,
    refetchInterval: 5000,
  });

  const experiments = useMemo(
    () => sortExperiments(experimentsQuery.data?.experiments ?? []),
    [experimentsQuery.data],
  );
  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      experiments.filter((exp) => {
        if (appTypeFilter !== "all" && normalizeAppType(exp) !== appTypeFilter) return false;
        if (statusFilter !== "all" && statusBucket(exp.status) !== statusFilter) return false;
        if (axisFilter !== "all" && normalizeAxis(exp) !== axisFilter) return false;
        if (designFilter !== "all" && normalizeDesign(exp) !== designFilter) return false;
        if (!q) return true;
        return [exp.name, exp.experimentId, exp.task, exp.appType, exp.status, exp.personaModel]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(q);
      }),
    [experiments, q, appTypeFilter, statusFilter, axisFilter, designFilter],
  );
  const filtersActive =
    q !== "" ||
    appTypeFilter !== "all" ||
    statusFilter !== "all" ||
    axisFilter !== "all" ||
    designFilter !== "all";

  const clearFilters = () => {
    setQuery("");
    setAppTypeFilter("all");
    setStatusFilter("all");
    setAxisFilter("all");
    setDesignFilter("all");
    setOpenHeader(null);
  };

  const deleteMutation = useMutation({
    mutationFn: (experimentId: string) => api.deleteExperiment(experimentId),
    onSuccess: () => {
      setDeleteError(null);
      setPendingDeleteId(null);
      void queryClient.invalidateQueries({ queryKey: ["experiments"] });
      void queryClient.invalidateQueries({ queryKey: ["harbor-jobs"] });
    },
    onError: (error) => {
      setDeleteError(
        error instanceof ApiError ? error.message : t("experiments.list.error.delete"),
      );
    },
  });

  const handleDelete = (exp: ExperimentSummary) => {
    deleteMutation.mutate(exp.experimentId);
  };

  useEffect(() => {
    if (!pendingDeleteId) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setPendingDeleteId(null);
    }
    function onDown(e: MouseEvent) {
      const el = e.target as HTMLElement | null;
      if (el?.closest("[data-exp-delete-confirm]") || el?.closest("[data-exp-delete-trigger]")) {
        return;
      }
      setPendingDeleteId(null);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [pendingDeleteId]);

  if (experimentsQuery.isLoading) {
    return <p className="text-[13px] text-text-dim">{t("experiments.list.loading")}</p>;
  }

  if (experimentsQuery.isError) {
    return (
      <StudioGlassPanel className="px-6 py-10 text-center">
        <p className="text-[13px] text-text-dim">{t("experiments.list.error.load")}</p>
        <button
          type="button"
          onClick={() => experimentsQuery.refetch()}
          className={`mt-3 inline-flex items-center rounded-md px-3 py-1.5 text-[13px] text-text-main glass-tile ${FOCUS_RING}`}
        >
          {t("experiments.list.retry")}
        </button>
      </StudioGlassPanel>
    );
  }

  if (experiments.length === 0) {
    return (
      <StudioGlassPanel className="px-6 py-14 text-center">
        <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-md glass-tile">
          <Sym name="science" size={26} className="text-text-dim" />
        </div>
        <h2 className="font-display text-[15px] font-semibold text-text-main">
          {t("experiments.list.empty.title")}
        </h2>
        <p className="mx-auto mt-2 max-w-md text-[14px] leading-relaxed text-text-variant">
          {t("experiments.list.empty.description")}
        </p>
        <button
          type="button"
          onClick={onNew}
          className={`mt-4 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-[14px] text-on-primary glow transition hover:bg-primary-dim active:scale-[0.97] ${FOCUS_RING}`}
        >
          <Sym name="add" size={16} />
          {t("experiments.list.newExperiment")}
        </button>
      </StudioGlassPanel>
    );
  }

  return (
    <div className="space-y-3">
      {deleteError ? (
        <p className="rounded-md bg-danger/10 px-3 py-2 text-[12.5px] text-danger" role="alert">
          {deleteError}
        </p>
      ) : null}
      <StudioGlassPanel className="relative z-20 overflow-visible p-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex h-8 min-w-0 flex-1 items-center rounded-lg glass-tile backdrop-blur focus-within:border-primary/50">
            <Sym name="search" size={16} className="ml-3 flex-none text-text-dim" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("experiments.list.searchPlaceholder")}
              className="h-full w-full min-w-0 bg-transparent px-3 text-[14px] text-text-main outline-none placeholder:text-text-variant"
            />
          </div>
          {filtersActive ? (
            <button
              type="button"
              onClick={clearFilters}
              className={`inline-flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-[12px] text-text-dim hover:text-text-main ${FOCUS_RING}`}
            >
              <Sym name="filter_alt_off" size={14} />
              {t("experiments.list.clear")}
            </button>
          ) : null}
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <FilterMenu
            label={t("experiments.list.filter.label.app")}
            value={appTypeFilter}
            options={APP_TYPE_OPTIONS.map((value) => ({
              value,
              label: t(APP_TYPE_LABELS[value]),
            }))}
            open={openHeader === "app"}
            onToggle={() => setOpenHeader((v) => (v === "app" ? null : "app"))}
            onChange={setAppTypeFilter}
          />
          <FilterMenu
            label={t("experiments.list.filter.label.axis")}
            value={axisFilter}
            options={AXIS_OPTIONS.map((value) => ({
              value,
              label: t(AXIS_LABELS[value]),
            }))}
            open={openHeader === "axis"}
            onToggle={() => setOpenHeader((v) => (v === "axis" ? null : "axis"))}
            onChange={setAxisFilter}
          />
          <FilterMenu
            label={t("experiments.list.filter.label.type")}
            value={designFilter}
            options={DESIGN_OPTIONS.map((value) => ({
              value,
              label: t(DESIGN_LABELS[value]),
            }))}
            open={openHeader === "type"}
            onToggle={() => setOpenHeader((v) => (v === "type" ? null : "type"))}
            onChange={setDesignFilter}
          />
          <FilterMenu
            label={t("experiments.list.filter.label.status")}
            value={statusFilter}
            options={STATUS_OPTIONS.map((value) => ({
              value,
              label: t(STATUS_LABELS[value]),
            }))}
            open={openHeader === "status"}
            onToggle={() => setOpenHeader((v) => (v === "status" ? null : "status"))}
            onChange={setStatusFilter}
          />
          <span className="ml-auto font-mono text-[12px] text-text-dim">
            {filtered.length === experiments.length
              ? t("experiments.list.count.total", { count: experiments.length })
              : t("experiments.list.count.filtered", {
                  count: filtered.length,
                  total: experiments.length,
                })}
          </span>
        </div>
      </StudioGlassPanel>

      {filtered.length === 0 ? (
        <StudioGlassPanel className="px-6 py-10 text-center">
          <p className="text-[13px] text-text-dim">
            {filtersActive
              ? t("experiments.list.noMatch.filters")
              : t("experiments.list.noMatch.query", { query })}
          </p>
        </StudioGlassPanel>
      ) : (
        <StudioGlassPanel className="overflow-visible rounded-xl">
          <div
            className={`${EXP_GRID} border-b border-outline/40 px-4 py-2 text-[11px] uppercase tracking-wide text-text-dim`}
          >
            <span>{t("experiments.list.column.experiment")}</span>
            <span>{t("experiments.list.column.app")}</span>
            <span>{t("experiments.list.column.axis")}</span>
            <span>{t("experiments.list.column.type")}</span>
            <span>{t("experiments.list.column.trials")}</span>
            <span>{t("experiments.list.column.time")}</span>
            <span>{t("experiments.list.column.cost")}</span>
            <span>{t("experiments.list.column.started")}</span>
            <span className="justify-self-end">{t("experiments.list.column.status")}</span>
            <span className="sr-only">{t("experiments.list.column.actions")}</span>
          </div>
          <ul className="divide-y divide-outline-dim">
            {filtered.map((exp) => (
              <li
                key={exp.experimentId}
                className={`group relative ${pendingDeleteId === exp.experimentId ? "z-30" : ""}`}
              >
                <ExperimentRow
                  exp={exp}
                  onOpen={() => onOpen(exp.experimentId)}
                  confirming={pendingDeleteId === exp.experimentId}
                  onAskDelete={() => setPendingDeleteId(exp.experimentId)}
                  onCancelDelete={() => setPendingDeleteId(null)}
                  onConfirmDelete={() => handleDelete(exp)}
                  deleting={deleteMutation.isPending && deleteMutation.variables === exp.experimentId}
                />
              </li>
            ))}
          </ul>
        </StudioGlassPanel>
      )}
    </div>
  );
}

function FilterMenu<T extends string>({
  label,
  open,
  onToggle,
  value,
  options,
  onChange,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  value: T | "all";
  options: { value: T; label: string }[];
  onChange: (v: T | "all") => void;
}) {
  const { t } = useI18n();
  const allLabel = t("experiments.list.filter.all");
  const active = value !== "all";
  const selected =
    value === "all"
      ? allLabel
      : (options.find((o) => o.value === value)?.label ?? allLabel);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={label}
        className={`inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] ${FOCUS_RING} ${
          active
            ? "bg-primary/12 font-medium text-primary"
            : "glass-tile glass-tile--hover text-text-variant hover:text-text-main"
        }`}
      >
        <span className="text-[11px] uppercase tracking-wide opacity-70">{label}</span>
        <span>{selected}</span>
        <Sym name="arrow_drop_down" size={16} className="opacity-70" />
      </button>
      {open ? (
        <div
          role="listbox"
          className="absolute left-0 top-full z-30 mt-1 min-w-[9rem] rounded-lg border border-outline/40 bg-surface p-1 shadow-lg"
        >
          <HeaderMenuItem
            label={allLabel}
            active={value === "all"}
            onClick={() => {
              onChange("all");
              onToggle();
            }}
          />
          {options.map((o) => (
            <HeaderMenuItem
              key={o.value}
              label={o.label}
              active={value === o.value}
              onClick={() => {
                onChange(o.value);
                onToggle();
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function HeaderMenuItem({
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
      className={`flex w-full items-center rounded-md px-2 py-1 text-left text-[12.5px] ${FOCUS_RING} ${
        active ? "bg-primary/12 font-semibold text-primary" : "text-text-variant hover:bg-surface-high/50"
      }`}
    >
      {label}
    </button>
  );
}

function fmtDuration(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return s > 0 ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function fmtCost(usd: number | null | undefined): string {
  if (typeof usd !== "number" || !Number.isFinite(usd)) return "—";
  if (usd >= 1) return `$${usd.toFixed(2)}`;
  if (usd >= 0.01) return `$${usd.toFixed(3)}`;
  if (usd > 0) return `$${usd.toFixed(4)}`;
  return "—";
}

function ExperimentRow({
  exp,
  onOpen,
  confirming,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
  deleting,
}: {
  exp: ExperimentSummary;
  onOpen: () => void;
  confirming: boolean;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  deleting: boolean;
}) {
  const { t } = useI18n();
  const total = exp.progress?.trialCount ?? 0;
  const done = exp.progress?.completedTrials ?? 0;
  const model = (exp.personaModel ?? "").split("/").pop();
  const jobs = exp.jobNames ?? [];
  const jobLine =
    jobs.length > 0
      ? jobs.length === 1
        ? jobs[0]
        : `${jobs[0]}  ${t("experiments.list.jobs.additional", { count: jobs.length - 1 })}`
      : exp.experimentId;
  const meta = [
    exp.armCount ? t("experiments.list.meta.arms", { count: exp.armCount }) : null,
    typeof exp.perArm === "number" && exp.perArm > 0
      ? t("experiments.list.meta.perArm", { count: exp.perArm })
      : null,
    model || null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className={`${EXP_GRID} px-4 py-3 transition hover:bg-surface-high/25`}>
      <button type="button" onClick={onOpen} className={`min-w-0 text-left ${FOCUS_RING}`}>
        <p className="truncate font-display text-[14.5px] font-semibold leading-snug text-text-main">
          {exp.name || exp.experimentId}
        </p>
        <p className="truncate font-mono text-[12px] text-text-dim" title={jobs.join(" · ")}>
          {jobLine}
        </p>
        {meta ? <p className="mt-0.5 truncate text-[11.5px] text-text-dim">{meta}</p> : null}
      </button>

      <button type="button" onClick={onOpen} className={`min-w-0 text-left ${FOCUS_RING}`}>
        <AppTypeTag type={normalizeAppType(exp)} />
      </button>

      <button type="button" onClick={onOpen} className={`min-w-0 text-left ${FOCUS_RING}`}>
        {exp.axis ? <AxisBadge axis={exp.axis} /> : <span className="text-[13px] text-text-dim">—</span>}
      </button>

      <button type="button" onClick={onOpen} className={`min-w-0 text-left ${FOCUS_RING}`}>
        {exp.designType ? (
          <span className="inline-flex items-center rounded-md bg-primary/12 px-2 py-0.5 text-[11px] font-semibold text-primary">
            {shortDesign(exp.designType, t)}
          </span>
        ) : (
          <span className="text-[13px] text-text-dim">—</span>
        )}
      </button>

      <button
        type="button"
        onClick={onOpen}
        className={`text-left font-mono text-[13px] tabular-nums text-text-main ${FOCUS_RING}`}
      >
        {total > 0 ? `${done}/${total}` : "—"}
      </button>
      <button
        type="button"
        onClick={onOpen}
        className={`text-left font-mono text-[13px] tabular-nums text-text-variant ${FOCUS_RING}`}
      >
        {fmtDuration(exp.durationSeconds)}
      </button>
      <button
        type="button"
        onClick={onOpen}
        className={`text-left font-mono text-[13px] tabular-nums text-text-main ${FOCUS_RING}`}
      >
        {fmtCost(exp.costUsd)}
      </button>
      <button
        type="button"
        onClick={onOpen}
        className={`whitespace-nowrap text-left text-[13px] text-text-variant ${FOCUS_RING}`}
      >
        {fmtRunDate(exp.createdAt)}
      </button>
      <button type="button" onClick={onOpen} className={`justify-self-end ${FOCUS_RING}`}>
        <StatusChip status={exp.status} />
      </button>
      <div className="relative justify-self-end">
        {confirming ? (
          <div
            data-exp-delete-confirm
            className="absolute right-0 top-1/2 z-30 flex -translate-y-1/2 items-center gap-2 rounded-lg border border-outline/50 bg-[rgb(var(--surface-lowest))] px-2.5 py-1.5 shadow-xl"
          >
            <p className="whitespace-nowrap text-[12.5px] text-text-main">
              {t("experiments.list.delete.confirm")}
            </p>
            <button
              type="button"
              onClick={onCancelDelete}
              className={`rounded-md px-2 py-1 text-[12px] font-medium text-text-variant hover:bg-surface-high/70 hover:text-text-main ${FOCUS_RING}`}
            >
              {t("experiments.list.delete.cancel")}
            </button>
            <button
              type="button"
              disabled={deleting}
              onClick={onConfirmDelete}
              className={`rounded-md bg-danger px-2 py-1 text-[12px] font-semibold text-white hover:bg-danger/90 disabled:opacity-50 ${FOCUS_RING}`}
            >
              {deleting ? t("experiments.list.delete.deleting") : t("experiments.list.delete.confirmButton")}
            </button>
          </div>
        ) : (
          <button
            type="button"
            data-exp-delete-trigger
            aria-label={t("experiments.list.delete.ariaLabel", {
              name: exp.name || exp.experimentId,
            })}
            disabled={deleting}
            onClick={onAskDelete}
            className={`grid h-8 w-8 place-items-center rounded-md text-text-dim opacity-0 transition hover:bg-danger/10 hover:text-danger group-hover:opacity-100 disabled:opacity-40 ${FOCUS_RING}`}
          >
            <Sym name="delete" size={16} />
          </button>
        )}
      </div>
    </div>
  );
}
