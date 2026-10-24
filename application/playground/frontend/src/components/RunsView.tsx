/**
 * RunsView: Harbor job history inside Playground.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { RunDetail } from "./RunDetail";
import { HarborJobDetail } from "./HarborJobDetail";
import { FOCUS_RING, Sym } from "./cockpit/cockpitShared";
import { AppTypeTag } from "./runsShared";
import { useI18n } from "@/i18n/I18nProvider";
import {
  StudioGlassPanel,
  StudioMeshShell,
  StudioPageFrame,
  StudioPageHeader,
  StudioToolbarButton,
} from "./studio/StudioShell";
import { api, ApiError } from "@/lib/api";
import {
  jobDisplayIdentity,
  parseExperimentArmJob,
  experimentArmDisplayLabel,
} from "@/lib/jobDisplay";
import {
  deriveHarborJobListStatus,
  harborJobListStatusLabel,
} from "@/lib/trialStatus";
import type { HarborJobListStatus, HarborJobSummary } from "@/lib/types";

export interface RunsViewProps {
  harborJobId: string | null;
  harborTrialId: string | null;
  openHarborJob: (jobName: string) => void;
  openHarborTrial: (jobName: string, trialName: string) => void;
  backToList: () => void;
  backToHarborJob: () => void;
  onClose: () => void;
  backLabel?: string;
}

export function RunsView({
  harborJobId,
  harborTrialId,
  openHarborJob,
  openHarborTrial,
  backToList,
  backToHarborJob,
  onClose,
  backLabel,
}: RunsViewProps) {
  const { t } = useI18n();
  const resolvedBackLabel = backLabel ?? t("runs.back");
  if (harborJobId && harborTrialId) {
    return (
      <StudioMeshShell>
        <RunDetail
          harborTrial={{ jobName: harborJobId, trialName: harborTrialId }}
          onBack={backToHarborJob}
        />
      </StudioMeshShell>
    );
  }
  if (harborJobId) {
    return (
      <StudioMeshShell>
        <HarborJobDetail
          jobName={harborJobId}
          onBack={backToList}
          onOpenTrial={(trialName) => openHarborTrial(harborJobId, trialName)}
        />
      </StudioMeshShell>
    );
  }
  return (
    <HarborJobsList
      openHarborJob={openHarborJob}
      onClose={onClose}
      backLabel={resolvedBackLabel}
    />
  );
}

interface HarborJobsListProps {
  openHarborJob: (jobName: string) => void;
  onClose: () => void;
  backLabel: string;
}

function sortHarborJobs(jobs: HarborJobSummary[]): HarborJobSummary[] {
  return [...jobs].sort((a, b) => {
    const ta = Date.parse(a.startedAt ?? a.updatedAt ?? "") || 0;
    const tb = Date.parse(b.startedAt ?? b.updatedAt ?? "") || 0;
    return tb - ta;
  });
}

function formatJobTimeFull(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const date = new Date(t);
  const y = date.getFullYear();
  const mo = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  const h = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  const s = String(date.getSeconds()).padStart(2, "0");
  return `${y}-${mo}-${d} ${h}:${mi}:${s}`;
}

function harborJobAppType(job: HarborJobSummary): string {
  const explicit = (job.applicationType ?? "").toString().toLowerCase();
  if (explicit && explicit !== "unknown") return explicit;
  const name = job.jobName.toLowerCase();
  if (name.includes("survey")) return "survey";
  if (
    name.includes("web") ||
    name.includes("playwright") ||
    name.includes("cocoa")
  )
    return "web";
  if (
    name.includes("computer-use") ||
    name.includes("os-app") ||
    name.includes("cua")
  )
    return "os-app";
  if (name.includes("appworld")) return "os-app";
  return "chatbot";
}

/** Shared column template for the Harbor jobs table (header + rows + skeleton). */
const HARBOR_JOBS_GRID =
  "grid grid-cols-[minmax(0,1fr)_5.75rem_9.75rem_4.25rem_minmax(5.5rem,6.25rem)_2.25rem] items-center gap-x-5";

type AppTypeFilter = "all" | "chatbot" | "survey" | "web" | "os-app";
type SourceFilter = "all" | "playground" | "experiment";
type StatusFilter = "all" | HarborJobListStatus;

function jobSource(job: HarborJobSummary): "playground" | "experiment" {
  if (job.source === "experiment" || job.source === "playground") return job.source;
  return job.jobName.startsWith("exp-") ? "experiment" : "playground";
}

const APP_TYPE_FILTER_OPTIONS: { value: Exclude<AppTypeFilter, "all"> }[] = [
  { value: "chatbot" },
  { value: "survey" },
  { value: "web" },
  { value: "os-app" },
];

const STATUS_FILTER_OPTIONS: { value: Exclude<StatusFilter, "all"> }[] = [
  { value: "running" },
  { value: "success" },
  { value: "failed" },
];

function harborJobSearchHaystack(job: HarborJobSummary): string {
  const status = deriveHarborJobListStatus(job);
  const timeIso = job.startedAt ?? job.updatedAt;
  const appType = harborJobAppType(job);
  const identity = jobDisplayIdentity(job.jobName, appType);
  return [
    job.jobName,
    job.taskTitle,
    job.taskName,
    job.domain,
    job.difficulty,
    ...(job.tags ?? []),
    job.arm,
    job.armLabel,
    job.cellId,
    ...(Object.values(job.factorLevels ?? {})),
    identity.title,
    identity.shortId,
    parseExperimentArmJob(job.jobName)?.experimentId,
    parseExperimentArmJob(job.jobName)?.launchHash,
    appType,
    jobSource(job),
    harborJobListStatusLabel(status),
    formatJobTimeFull(timeIso),
    `${job.completedTrials ?? job.trialCount}/${job.trialCount}`,
  ]
    .join(" ")
    .toLowerCase();
}

function filterHarborJobs(
  jobs: HarborJobSummary[],
  {
    searchQuery,
    appTypeFilter,
    sourceFilter,
    statusFilter,
  }: {
    searchQuery: string;
    appTypeFilter: AppTypeFilter;
    sourceFilter: SourceFilter;
    statusFilter: StatusFilter;
  },
): HarborJobSummary[] {
  const q = searchQuery.trim().toLowerCase();
  return jobs.filter((job) => {
    if (appTypeFilter !== "all" && harborJobAppType(job) !== appTypeFilter)
      return false;
    if (sourceFilter !== "all" && jobSource(job) !== sourceFilter) return false;
    if (
      statusFilter !== "all" &&
      deriveHarborJobListStatus(job) !== statusFilter
    )
      return false;
    if (!q) return true;
    return harborJobSearchHaystack(job).includes(q);
  });
}

type RunListGroup = {
  id: string;
  source: "experiment" | "playground";
  launchHash: string | null;
  title: string;
  jobs: HarborJobSummary[];
};

function groupHarborJobs(jobs: HarborJobSummary[]): RunListGroup[] {
  const groups = new Map<string, RunListGroup>();
  const entries: RunListGroup[] = [];
  for (const job of jobs) {
    const exp = parseExperimentArmJob(job.jobName);
    const identity = jobDisplayIdentity(job.jobName, harborJobAppType(job));
    const title = (job.taskTitle ?? "").trim() || identity.title;
    const id =
      (job.experimentId ?? "").trim() ||
      exp?.experimentId ||
      job.jobName;
    const existing = groups.get(id);
    if (existing) {
      existing.jobs.push(job);
      continue;
    }
    const group: RunListGroup = {
      id,
      source: exp ? "experiment" : "playground",
      launchHash: exp?.launchHash ?? identity.shortId,
      title,
      jobs: [job],
    };
    groups.set(id, group);
    entries.push(group);
  }
  for (const entry of entries) {
    if (entry.source !== "experiment") continue;
    entry.jobs.sort((a, b) => {
      const aa = parseExperimentArmJob(a.jobName)?.armIndex ?? 0;
      const bb = parseExperimentArmJob(b.jobName)?.armIndex ?? 0;
      return aa - bb;
    });
  }
  return entries;
}

function runsFiltersActive(
  searchQuery: string,
  appTypeFilter: AppTypeFilter,
  sourceFilter: SourceFilter,
  statusFilter: StatusFilter,
): boolean {
  return (
    searchQuery.trim() !== "" ||
    appTypeFilter !== "all" ||
    sourceFilter !== "all" ||
    statusFilter !== "all"
  );
}

const JOB_STATUS_STYLES: Record<
  HarborJobListStatus,
  { className: string; icon: string; fill?: 0 | 1 }
> = {
  running: {
    className: "bg-warn/10 text-warn",
    icon: "autorenew",
  },
  success: {
    className: "bg-secondary/10 text-secondary",
    icon: "check_circle",
    fill: 1,
  },
  failed: {
    className: "bg-danger/10 text-danger",
    icon: "error",
    fill: 1,
  },
};

const JOB_PROGRESS_STYLES: Record<
  HarborJobListStatus,
  { bar: string; track?: string }
> = {
  running: {
    bar: "bg-warn animate-pulse",
  },
  success: {
    bar: "bg-secondary",
  },
  failed: {
    bar: "bg-danger",
  },
};

function JobTrialProgress({
  job,
  status,
}: {
  job: HarborJobSummary;
  status: HarborJobListStatus;
}) {
  const { t } = useI18n();
  const completed = job.completedTrials ?? 0;
  const total = Math.max(job.trialCount ?? 0, 0);
  const ratio = total > 0 ? Math.min(1, completed / total) : 0;
  const style = JOB_PROGRESS_STYLES[status];
  const label =
    total === 0
      ? t("runs.noTrials")
      : t("runs.trialsComplete", { completed, total });

  return (
    <div
      className="mt-1.5 h-1.5 min-w-[5rem] overflow-hidden rounded-full bg-surface-high"
      role="progressbar"
      aria-valuenow={completed}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-label={label}
    >
      <div
        className={`h-full rounded-full transition-[width] duration-300 ${style.bar}`}
        style={{ width: `${ratio * 100}%` }}
      />
    </div>
  );
}

const JOB_TRIAL_COUNT_STYLES: Record<HarborJobListStatus, string> = {
  running: "bg-warn/10",
  success: "bg-secondary/10",
  failed: "bg-danger/10",
};

function JobTrialCountCell({
  job,
  status,
  onOpen,
}: {
  job: HarborJobSummary;
  status: HarborJobListStatus;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const completed = job.completedTrials ?? 0;
  const total = Math.max(job.trialCount ?? 0, 0);
  const inProgress = status === "running" && completed < total;
  const detail =
    total === 0
      ? t("runs.noTrials")
      : inProgress
        ? t("runs.trialsComplete", { completed, total })
        : t("runs.trialCount", { count: total });

  return (
    <button
      type="button"
      onClick={onOpen}
      title={detail}
      className={`justify-self-center ${FOCUS_RING}`}
    >
      <div
        className={`inline-flex min-w-[3.5rem] flex-col items-center rounded-lg px-2.5 py-1.5 shadow-[inset_0_1px_0_rgb(255_255_255/0.06)] ${JOB_TRIAL_COUNT_STYLES[status]}`}
      >
        <span className="font-display text-[20px] font-bold leading-none tabular-nums text-text-main">
          {inProgress ? (
            <>
              {completed}
              <span className="text-[14px] font-semibold text-text-dim">
                /{total}
              </span>
            </>
          ) : (
            total
          )}
        </span>
        <span className="mt-0.5 font-mono text-[11px] uppercase tracking-wide text-text-dim">
          {t("runs.trialUnit", { count: total })}
        </span>
      </div>
    </button>
  );
}

function JobListIdentity({
  job,
  onOpen,
  inGroup,
}: {
  job: HarborJobSummary;
  onOpen: () => void;
  inGroup?: boolean;
}) {
  const { t } = useI18n();
  const appType = harborJobAppType(job);
  const status = deriveHarborJobListStatus(job);
  const source = jobSource(job);
  const identity = jobDisplayIdentity(job.jobName, appType);
  const exp = parseExperimentArmJob(job.jobName);
  const armLabel =
    (job.armLabel ?? "").trim() ||
    experimentArmDisplayLabel({
      arm: job.arm,
      factorLevels: job.factorLevels,
      cellId: job.cellId,
    });
  // Prefer title derived from task.toml ``[task].name``.
  // Inside an experiment group, prefer the factor / combination label.
  const title = !inGroup
    ? (job.taskTitle ?? "").trim() || identity.title
    : armLabel ||
      (exp ? t("runs.arm", { index: exp.armIndex }) : null) ||
      identity.shortId ||
      t("runs.job");
  const metaChips = [
    inGroup && job.armBaseline ? "control" : null,
    job.domain,
    job.difficulty,
  ]
    .map((value) => (value ?? "").trim())
    .filter(Boolean);
  const subtitle = inGroup
    ? job.jobName
    : identity.shortId && identity.shortId !== title
      ? identity.shortId
      : job.taskName && job.taskName !== title
        ? job.taskName
        : title !== job.jobName
          ? job.jobName
          : null;

  return (
    <button
      type="button"
      onClick={onOpen}
      className={`min-w-0 text-left ${FOCUS_RING}`}
      title={job.taskName || job.jobName}
    >
      <div className="flex min-w-0 items-center gap-2">
        <p className="truncate font-display text-[15px] font-semibold leading-snug text-text-main group-hover:text-primary">
          {title}
        </p>
        {inGroup ? null : <JobSourceBadge source={source} />}
      </div>
      {subtitle ? (
        <p className="truncate font-mono text-[12px] tracking-wide text-text-dim">
          {subtitle}
        </p>
      ) : null}
      {metaChips.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {metaChips.map((chip) => (
            <span
              key={chip}
              className={
                chip === "control"
                  ? "rounded bg-primary/12 px-1.5 py-0.5 text-[11px] font-medium text-primary"
                  : "rounded glass-tile px-1.5 py-0.5 text-[11px] text-text-variant"
              }
            >
              {chip === "control" ? t("runs.armControl") : chip}
            </span>
          ))}
        </div>
      ) : null}
      <JobTrialProgress job={job} status={status} />
    </button>
  );
}

function HarborJobStatusBadge({ job }: { job: HarborJobSummary }) {
  const { t } = useI18n();
  const status = deriveHarborJobListStatus(job);
  const style = JOB_STATUS_STYLES[status];
  const label = harborJobListStatusLabel(status, t);
  const detail =
    status === "failed" && (job.failedTrials ?? 0) > 0
      ? t("runs.failedTrials", {
          statusLabel: label,
          count: job.failedTrials ?? 0,
        })
      : label;

  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 truncate rounded-md px-2 py-0.5 font-mono text-[12px] uppercase tracking-wide ${style.className}`}
      title={detail}
    >
      <Sym
        name={style.icon}
        size={12}
        fill={style.fill}
        className={
          status === "running" ? "shrink-0 animate-rb-spin" : "shrink-0"
        }
      />
      <span className="truncate">{label}</span>
    </span>
  );
}

function HarborJobsList({
  openHarborJob,
  onClose,
  backLabel,
}: HarborJobsListProps) {
  const { t, rich } = useI18n();
  const queryClient = useQueryClient();
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [appTypeFilter, setAppTypeFilter] = useState<AppTypeFilter>("all");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const harborQuery = useQuery({
    queryKey: ["harbor-jobs"],
    queryFn: api.listHarborJobs,
    refetchInterval: 5000,
  });
  const harborJobs = useMemo(
    () => sortHarborJobs(harborQuery.data?.jobs ?? []),
    [harborQuery.data],
  );
  const filteredJobs = useMemo(
    () =>
      filterHarborJobs(harborJobs, {
        searchQuery,
        appTypeFilter,
        sourceFilter,
        statusFilter,
      }),
    [harborJobs, searchQuery, appTypeFilter, sourceFilter, statusFilter],
  );
  const filtersActive = runsFiltersActive(
    searchQuery,
    appTypeFilter,
    sourceFilter,
    statusFilter,
  );

  const clearFilters = () => {
    setSearchQuery("");
    setAppTypeFilter("all");
    setSourceFilter("all");
    setStatusFilter("all");
  };

  const deleteMutation = useMutation({
    mutationFn: (jobName: string) => api.deleteHarborJob(jobName),
    onSuccess: () => {
      setDeleteError(null);
      void queryClient.invalidateQueries({ queryKey: ["harbor-jobs"] });
    },
    onError: (error) => {
      setDeleteError(
        error instanceof ApiError ? error.message : t("runs.couldNotDeleteJob"),
      );
    },
  });

  const deleteExperimentMutation = useMutation({
    mutationFn: async (entry: RunListGroup) => {
      try {
        await api.deleteExperiment(entry.id);
        return;
      } catch (error) {
        // Orphan arm folders (manifest already gone): delete each Harbor job.
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
        for (const job of entry.jobs) {
          await api.deleteHarborJob(job.jobName);
        }
      }
    },
    onSuccess: () => {
      setDeleteError(null);
      void queryClient.invalidateQueries({ queryKey: ["harbor-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["experiments"] });
    },
    onError: (error) => {
      setDeleteError(
        error instanceof ApiError
          ? error.message
          : t("runs.couldNotDeleteExperiment"),
      );
    },
  });

  // Confirmation now lives in an in-app popover on the trash button
  // (ConfirmDeleteButton), so these just fire the mutation.
  const handleDelete = (job: HarborJobSummary) => {
    deleteMutation.mutate(job.jobName);
  };

  const handleDeleteExperiment = (entry: RunListGroup) => {
    deleteExperimentMutation.mutate(entry);
  };

  return (
    <StudioMeshShell>
      <StudioPageFrame>
        <StudioPageHeader
          compact
          eyebrow={t("runs.eyebrow")}
          title={t("runs.title")}
          subtitle={
            rich("runs.jobsSubtitle", {
              path: (parts) => <span className="font-mono">{parts}</span>,
            })
          }
          meta={
            !harborQuery.isLoading && !harborQuery.isError ? (
              <span className="font-mono text-[13px] text-text-variant">
                {filtersActive
                  ? t("runs.filteredJobCount", {
                      shown: filteredJobs.length,
                      total: harborJobs.length,
                    })
                  : t("runs.jobCount", { count: harborJobs.length })}
              </span>
            ) : null
          }
          actions={
            <>
              <StudioToolbarButton icon="arrow_back" onClick={onClose}>
                {backLabel}
              </StudioToolbarButton>
              <StudioToolbarButton
                icon="refresh"
                onClick={() => harborQuery.refetch()}
                disabled={harborQuery.isFetching}
              >
                {harborQuery.isFetching
                  ? t("runs.refreshing")
                  : t("runs.refresh")}
              </StudioToolbarButton>
            </>
          }
        />
        {deleteError && (
          <p className="mb-4 text-[14px] text-danger" role="alert">
            {deleteError}
          </p>
        )}

        {harborQuery.isLoading ? (
          <ListLoading />
        ) : harborQuery.isError ? (
          <ListError
            error={harborQuery.error}
            onRetry={() => harborQuery.refetch()}
          />
        ) : harborJobs.length === 0 ? (
          <ListEmpty onClose={onClose} />
        ) : (
          <>
            <HarborJobsFilterBar
              searchQuery={searchQuery}
              onSearchQueryChange={setSearchQuery}
              appTypeFilter={appTypeFilter}
              onAppTypeFilterChange={setAppTypeFilter}
              sourceFilter={sourceFilter}
              onSourceFilterChange={setSourceFilter}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              onClearFilters={clearFilters}
              filtersActive={filtersActive}
            />
            {filteredJobs.length === 0 ? (
              <ListFilterEmpty onClearFilters={clearFilters} />
            ) : (
              <HarborJobsTable
                jobs={filteredJobs}
                onOpen={openHarborJob}
                onDelete={handleDelete}
                onDeleteExperiment={handleDeleteExperiment}
                deletingJobName={
                  deleteMutation.isPending ? deleteMutation.variables : null
                }
                deletingExperimentId={
                  deleteExperimentMutation.isPending
                    ? deleteExperimentMutation.variables?.id ?? null
                    : null
                }
              />
            )}
          </>
        )}
      </StudioPageFrame>
    </StudioMeshShell>
  );
}

function HarborJobsFilterBar({
  searchQuery,
  onSearchQueryChange,
  appTypeFilter,
  onAppTypeFilterChange,
  sourceFilter,
  onSourceFilterChange,
  statusFilter,
  onStatusFilterChange,
  onClearFilters,
  filtersActive,
}: {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  appTypeFilter: AppTypeFilter;
  onAppTypeFilterChange: (value: AppTypeFilter) => void;
  sourceFilter: SourceFilter;
  onSourceFilterChange: (value: SourceFilter) => void;
  statusFilter: StatusFilter;
  onStatusFilterChange: (value: StatusFilter) => void;
  onClearFilters: () => void;
  filtersActive: boolean;
}) {
  const { t } = useI18n();
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const appOptions = APP_TYPE_FILTER_OPTIONS.map((option) => ({
    value: option.value,
    label:
      option.value === "chatbot"
        ? t("runs.appType.chatbot")
        : option.value === "survey"
          ? t("runs.appType.survey")
          : option.value === "web"
            ? t("runs.appType.web")
            : t("runs.appType.osApp"),
  }));
  const sourceOptions: { value: Exclude<SourceFilter, "all">; label: string }[] = [
    { value: "playground", label: t("runs.source.playground") },
    { value: "experiment", label: t("runs.source.experiment") },
  ];
  const statusOptions = STATUS_FILTER_OPTIONS.map((option) => ({
    value: option.value,
    label:
      option.value === "running"
        ? t("runs.status.running")
        : option.value === "success"
          ? t("runs.status.success")
          : t("runs.status.failed"),
  }));

  return (
    <StudioGlassPanel className="relative z-20 mb-3 overflow-visible p-3">
      <div className="flex min-w-0 items-center gap-2">
        <div className="flex h-8 min-w-0 flex-1 items-center rounded-lg glass-tile backdrop-blur transition-colors focus-within:border-primary/50">
          <Sym name="search" size={16} className="ml-3 flex-none text-text-dim" />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => onSearchQueryChange(e.target.value)}
            placeholder={t("runs.searchPlaceholder")}
            aria-label={t("runs.search")}
            className="h-full w-full min-w-0 bg-transparent px-3 text-[15px] text-text-main outline-none placeholder:text-text-variant"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => onSearchQueryChange("")}
              aria-label={t("runs.clearSearch")}
              className={`mr-2 flex-none rounded p-1 text-text-dim transition-colors hover:bg-surface-high hover:text-text-main ${FOCUS_RING}`}
            >
              <Sym name="close" size={16} />
            </button>
          )}
        </div>
        {filtersActive ? (
          <button
            type="button"
            onClick={onClearFilters}
            className={`inline-flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-[12px] text-text-dim hover:text-text-main ${FOCUS_RING}`}
          >
            <Sym name="filter_alt_off" size={14} />
            {t("runs.clearFilters")}
          </button>
        ) : null}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <RunsFilterMenu
          label={t("runs.appType")}
          value={appTypeFilter}
          options={appOptions}
          open={openMenu === "app"}
          onToggle={() => setOpenMenu((v) => (v === "app" ? null : "app"))}
          onChange={onAppTypeFilterChange}
        />
        <RunsFilterMenu
          label={t("runs.source")}
          value={sourceFilter}
          options={sourceOptions}
          open={openMenu === "source"}
          onToggle={() => setOpenMenu((v) => (v === "source" ? null : "source"))}
          onChange={onSourceFilterChange}
        />
        <RunsFilterMenu
          label={t("runs.status")}
          value={statusFilter}
          options={statusOptions}
          open={openMenu === "status"}
          onToggle={() => setOpenMenu((v) => (v === "status" ? null : "status"))}
          onChange={onStatusFilterChange}
        />
      </div>
    </StudioGlassPanel>
  );
}

function selectedFilterLabel<T extends string>(
  value: T | "all",
  options: { value: T; label: string }[],
  allLabel: string,
): string {
  if (value === "all") return allLabel;
  return options.find((option) => option.value === value)?.label ?? allLabel;
}

function RunsFilterMenu<T extends string>({
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
  onChange: (value: T | "all") => void;
}) {
  const { t } = useI18n();
  const allLabel = t("runs.all");
  const active = value !== "all";
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
        <span>{selectedFilterLabel(value, options, allLabel)}</span>
        <Sym name="arrow_drop_down" size={16} className="opacity-70" />
      </button>
      {open ? (
        <div
          role="listbox"
          className="absolute left-0 top-full z-30 mt-1 min-w-[9rem] rounded-lg border border-outline/40 bg-surface p-1 shadow-lg"
        >
          <RunsFilterMenuItem
            label={allLabel}
            active={value === "all"}
            onClick={() => {
              onChange("all");
              onToggle();
            }}
          />
          {options.map((option) => (
            <RunsFilterMenuItem
              key={option.value}
              label={option.label}
              active={value === option.value}
              onClick={() => {
                onChange(option.value);
                onToggle();
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RunsFilterMenuItem({
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
        active
          ? "bg-primary/12 font-semibold text-primary"
          : "text-text-variant hover:bg-surface-high/50"
      }`}
    >
      {label}
    </button>
  );
}

function JobSourceBadge({ source }: { source: "playground" | "experiment" }) {
  const { t } = useI18n();
  const experiment = source === "experiment";
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium ${
        experiment
          ? "bg-primary/12 text-primary"
          : "bg-secondary/12 text-secondary"
      }`}
    >
      <Sym name={experiment ? "science" : "play_circle"} size={12} />
      {experiment
        ? t("runs.source.experiment")
        : t("runs.source.playground")}
    </span>
  );
}

/** Trash button that reveals a small in-app confirm popover on click (replaces
 * the browser-native window.confirm). */
function ConfirmDeleteButton({
  message,
  onConfirm,
  busy,
  ariaLabel,
  title,
  buttonClassName,
}: {
  message: string;
  onConfirm: () => void;
  busy?: boolean;
  ariaLabel: string;
  title: string;
  buttonClassName: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={wrapRef} className="relative inline-flex">
      <button
        type="button"
        aria-label={ariaLabel}
        title={title}
        disabled={busy}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className={`${buttonClassName} ${open ? "opacity-100" : ""}`}
      >
        <Sym
          name={busy ? "autorenew" : "delete"}
          size={16}
          className={busy ? "animate-rb-spin" : ""}
        />
      </button>
      {open ? (
        <div
          role="dialog"
          onClick={(e) => e.stopPropagation()}
          className="absolute right-0 top-full z-50 mt-1 w-64 rounded-lg border border-outline/50 bg-[rgb(var(--surface-lowest))] p-3 text-left shadow-xl"
        >
          <p className="whitespace-pre-line text-[12px] leading-snug text-text-variant">
            {message}
          </p>
          <div className="mt-2.5 flex justify-end gap-2">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
              }}
              className={`rounded-md px-2.5 py-1 text-[12px] font-medium text-text-variant hover:bg-surface-high/70 hover:text-text-main ${FOCUS_RING}`}
            >
              {t("runs.cancel")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                onConfirm();
              }}
              className={`rounded-md bg-danger px-2.5 py-1 text-[12px] font-semibold text-white hover:bg-danger/90 disabled:opacity-50 ${FOCUS_RING}`}
            >
              {busy ? t("runs.deleting") : t("runs.delete")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function HarborJobsTable({
  jobs,
  onOpen,
  onDelete,
  onDeleteExperiment,
  deletingJobName,
  deletingExperimentId,
}: {
  jobs: HarborJobSummary[];
  onOpen: (jobName: string) => void;
  onDelete: (job: HarborJobSummary) => void;
  onDeleteExperiment: (entry: RunListGroup) => void;
  deletingJobName: string | null | undefined;
  deletingExperimentId: string | null | undefined;
}) {
  const { t } = useI18n();
  const entries = groupHarborJobs(jobs);
  return (
    <StudioGlassPanel className="overflow-visible rounded-xl">
      <div
        className={`${HARBOR_JOBS_GRID} border-b border-outline/40 px-4 py-2.5 text-[12px] uppercase tracking-wide text-text-dim`}
      >
        <span>{t("runs.job")}</span>
        <span>{t("runs.appType")}</span>
        <span>{t("runs.started")}</span>
        <span className="text-center">{t("runs.trials")}</span>
        <span className="justify-self-end">{t("runs.status")}</span>
        <span className="sr-only">{t("runs.actions")}</span>
      </div>
      <ul className="divide-y divide-outline-dim">
        {entries.map((entry) => {
          const deletingGroup = deletingExperimentId === entry.id;
          const showGroupDelete = entry.source === "experiment";
          return (
            <li key={entry.id} className="group/exp">
              <div className="flex items-center gap-2 bg-surface-high/25 px-4 py-2">
                <Sym
                  name={entry.source === "experiment" ? "science" : "play_circle"}
                  size={14}
                  className={
                    entry.source === "experiment"
                      ? "text-primary"
                      : "text-secondary"
                  }
                />
                <span className="min-w-0 truncate font-display text-[13px] font-semibold text-text-main">
                  {entry.title}
                </span>
                {entry.launchHash ? (
                  <span className="shrink-0 font-mono text-[12px] text-text-dim">
                    {entry.launchHash}
                  </span>
                ) : null}
                <span className="shrink-0 text-[12px] text-text-dim">
                  {t("runs.jobCount", { count: entry.jobs.length })}
                </span>
                <JobSourceBadge source={entry.source} />
                {showGroupDelete ? (
                  <div className="ml-auto">
                    <ConfirmDeleteButton
                      ariaLabel={t("runs.deleteExperimentAria", {
                        title: entry.title,
                      })}
                      title={t("runs.deleteExperiment")}
                      busy={deletingGroup}
                      message={t("runs.deleteExperimentConfirm", {
                        title: entry.title,
                        count: entry.jobs.length,
                      })}
                      onConfirm={() => onDeleteExperiment(entry)}
                      buttonClassName={`grid h-8 w-8 shrink-0 place-items-center rounded-md text-text-dim opacity-0 transition hover:bg-danger/10 hover:text-danger group-hover/exp:opacity-100 disabled:opacity-40 ${FOCUS_RING}`}
                    />
                  </div>
                ) : (
                  <span className="ml-auto" />
                )}
              </div>
              <ul className="divide-y divide-outline-dim">
                {entry.jobs.map((job) => (
                  <HarborJobRow
                    key={job.jobName}
                    job={job}
                    inGroup
                    onOpen={onOpen}
                    onDelete={onDelete}
                    deleting={
                      deletingJobName === job.jobName || deletingGroup
                    }
                  />
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
    </StudioGlassPanel>
  );
}

function HarborJobRow({
  job,
  inGroup,
  onOpen,
  onDelete,
  deleting,
}: {
  job: HarborJobSummary;
  inGroup?: boolean;
  onOpen: (jobName: string) => void;
  onDelete: (job: HarborJobSummary) => void;
  deleting: boolean;
}) {
  const { t } = useI18n();
  const timeIso = job.startedAt ?? job.updatedAt;
  return (
    <li className={`group ${inGroup ? "bg-surface/20" : ""}`}>
      <div className={`${HARBOR_JOBS_GRID} px-4 py-3.5 ${inGroup ? "pl-8" : ""}`}>
        <JobListIdentity
          job={job}
          inGroup={inGroup}
          onOpen={() => onOpen(job.jobName)}
        />
        <div className="min-w-0">
          <AppTypeTag type={harborJobAppType(job)} />
        </div>
        <button
          type="button"
          onClick={() => onOpen(job.jobName)}
          title={timeIso ?? undefined}
          className={`whitespace-nowrap text-left font-mono text-[13px] tabular-nums text-text-variant hover:text-text-main ${FOCUS_RING}`}
        >
          {formatJobTimeFull(timeIso)}
        </button>
        <JobTrialCountCell
          job={job}
          status={deriveHarborJobListStatus(job)}
          onOpen={() => onOpen(job.jobName)}
        />
        <div className="min-w-0 justify-self-end">
          <HarborJobStatusBadge job={job} />
        </div>
        <ConfirmDeleteButton
          ariaLabel={t("runs.deleteJobAria", { jobName: job.jobName })}
          title={t("runs.deleteJobAria", { jobName: job.jobName })}
          busy={deleting}
          message={t("runs.deleteConfirm", { jobName: job.jobName })}
          onConfirm={() => onDelete(job)}
          buttonClassName={`grid h-8 w-8 place-items-center rounded-md text-text-dim opacity-0 transition hover:bg-danger/10 hover:text-danger group-hover:opacity-100 disabled:opacity-40 ${FOCUS_RING}`}
        />
      </div>
    </li>
  );
}

function ListLoading() {
  return (
    <StudioGlassPanel className="rounded-xl" aria-hidden>
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className={`${HARBOR_JOBS_GRID} border-b border-outline-dim px-4 py-3.5 last:border-b-0`}
        >
          <div className="space-y-1.5">
            <div className="h-3.5 w-3/5 animate-rb-pulse rounded bg-surface-high" />
            <div className="h-2.5 w-16 animate-rb-pulse rounded bg-surface-high" />
            <div className="h-1 w-full animate-rb-pulse rounded-full bg-surface-high" />
          </div>
          <div className="h-3.5 w-14 animate-rb-pulse rounded bg-surface-high" />
          <div className="h-3.5 animate-rb-pulse rounded bg-surface-high" />
          <div className="mx-auto h-10 w-12 animate-rb-pulse rounded-lg bg-surface-high" />
          <div className="ml-auto h-3.5 w-16 animate-rb-pulse rounded bg-surface-high" />
        </div>
      ))}
    </StudioGlassPanel>
  );
}

function ListFilterEmpty({ onClearFilters }: { onClearFilters: () => void }) {
  const { t } = useI18n();
  return (
    <StudioGlassPanel className="px-6 py-12 text-center rise-in">
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-md glass-tile">
        <Sym name="search_off" size={24} className="text-text-dim" />
      </div>
      <h2 className="font-display text-[15px] font-semibold text-text-main">
        {t("runs.noMatching")}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-[15px] leading-relaxed text-text-variant">
        {t("runs.noMatchingDescription")}
      </p>
      <button
        type="button"
        onClick={onClearFilters}
        className={`mt-4 inline-flex items-center gap-1.5 rounded-md glass-tile glass-tile--hover px-4 py-2 text-[14px] text-text-variant transition hover:text-text-main ${FOCUS_RING}`}
      >
        <Sym name="filter_alt_off" size={16} />
        {t("runs.clearFilters")}
      </button>
    </StudioGlassPanel>
  );
}

function ListEmpty({ onClose }: { onClose: () => void }) {
  const { t, rich } = useI18n();
  return (
    <StudioGlassPanel className="px-6 py-14 text-center rise-in">
      <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-md glass-tile">
        <Sym name="history" size={26} className="text-text-dim" />
      </div>
      <h2 className="font-display text-[15px] font-semibold text-text-main">
        {t("runs.emptyTitle")}
      </h2>
      <p className="mx-auto mt-2 max-w-md text-[15px] leading-relaxed text-text-variant">
        {rich("runs.emptyDescription", {
          path: (parts) => <span className="font-mono">{parts}</span>,
        })}
      </p>
      <button
        type="button"
        onClick={onClose}
        className={`mt-4 inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-[14px] text-on-primary glow transition ease-out hover:bg-primary-dim active:scale-[0.97] ${FOCUS_RING}`}
      >
        <Sym name="play_arrow" fill={1} size={16} />
        {t("runs.backToHome")}
      </button>
    </StudioGlassPanel>
  );
}

function ListError({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  const message =
    error instanceof ApiError ? error.message : t("runs.loadErrorMessage");
  return (
    <StudioGlassPanel className="border-l-4 border-l-danger px-5 py-8 text-center rise-in">
      <h2 className="font-display text-[15px] font-semibold text-text-main">
        {t("runs.loadErrorTitle")}
      </h2>
      <p className="mx-auto mt-1.5 max-w-md break-words text-[15px] leading-relaxed text-text-variant">
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className={`mt-4 inline-flex items-center gap-1.5 rounded-md bg-danger/10 px-4 py-2 text-[14px] text-danger ${FOCUS_RING}`}
      >
        <Sym name="refresh" size={16} />
        {t("runs.tryAgain")}
      </button>
    </StudioGlassPanel>
  );
}

export default RunsView;
