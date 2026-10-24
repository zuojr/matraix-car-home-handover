import { useI18n } from "@/i18n/I18nProvider";
import type { ConfigOptionsResponse } from "@/lib/types";
import { FOCUS_RING, Sym } from "../cockpit/cockpitShared";
import { HarborJobDetail } from "../HarborJobDetail";
import { RunDetail } from "../RunDetail";
import {
  StudioMeshShell,
  StudioPageFrame,
  StudioPageHeader,
} from "../studio/StudioShell";
import { ExperimentDetail } from "./ExperimentDetail";
import { ExperimentRunConfigurator } from "./ExperimentRunConfigurator";
import { ExperimentsList } from "./ExperimentsList";
import { ExperimentTaskBrowser } from "./ExperimentTaskBrowser";
import { ExperimentTaskDetail } from "./ExperimentTaskDetail";

export interface ExperimentsWorkbenchProps {
  options: ConfigOptionsResponse | null;
  experimentId: string | null;
  experimentJob: string | null;
  experimentTrial: string | null;
  expScreen: string | null;
  expTask: string | null;
  expConfig: string | null;
  openExperiment: (id: string) => void;
  openExperimentRuns: () => void;
  openExperimentBrowse: () => void;
  openExperimentTask: (taskPath: string) => void;
  openExperimentConfigure: (taskPath: string) => void;
  openExperimentJob: (jobName: string) => void;
  openExperimentTrial: (jobName: string, trialName: string) => void;
  backToExperiment: () => void;
  backToExperimentJob: () => void;
}

type Screen = "browse" | "task" | "configure" | "runs" | "detail";

export function ExperimentsWorkbench({
  options,
  experimentId,
  experimentJob,
  experimentTrial,
  expScreen,
  expTask,
  expConfig,
  openExperiment,
  openExperimentRuns,
  openExperimentBrowse,
  openExperimentTask,
  openExperimentConfigure,
  openExperimentJob,
  openExperimentTrial,
  backToExperiment,
  backToExperimentJob,
}: ExperimentsWorkbenchProps) {
  const { t } = useI18n();
  // Drill-down: single persona trial (reuses the Runs trial view).
  if (experimentJob && experimentTrial) {
    return (
      <StudioMeshShell>
        <RunDetail
          harborTrial={{ jobName: experimentJob, trialName: experimentTrial }}
          onBack={backToExperimentJob}
        />
      </StudioMeshShell>
    );
  }

  // Drill-down: an arm's Harbor job (reuses the Runs job view).
  if (experimentJob) {
    return (
      <StudioMeshShell>
        <HarborJobDetail
          jobName={experimentJob}
          onBack={backToExperiment}
          onOpenTrial={(trialName) => openExperimentTrial(experimentJob, trialName)}
        />
      </StudioMeshShell>
    );
  }

  const screen: Screen = experimentId
    ? "detail"
    : expTask && expConfig
      ? "configure"
      : expTask
        ? "task"
        : expScreen === "runs"
          ? "runs"
          : "browse";

  const inTaskFlow = screen === "browse" || screen === "task" || screen === "configure";

  return (
    <StudioMeshShell>
      <StudioPageFrame fill={false}>
        <StudioPageHeader
          title={t("experiments.workbench.title")}
          subtitle={
            screen === "detail" ? (
              <nav className="flex min-w-0 items-center gap-1.5">
                <Sym name="chevron_right" size={15} className="text-text-dim" />
                <Crumb label={t("experiments.workbench.history")} onClick={openExperimentRuns} />
                <Sym name="chevron_right" size={15} className="text-text-dim" />
                <span className="truncate font-mono text-text-variant">{experimentId}</span>
              </nav>
            ) : screen === "runs" ? (
              <nav className="flex min-w-0 items-center gap-1.5">
                <Sym name="chevron_right" size={15} className="text-text-dim" />
                <span className="truncate">{t("experiments.workbench.history")}</span>
              </nav>
            ) : undefined
          }
          actions={
            <>
              <SegBtn
                icon="science"
                label={t("experiments.workbench.seg.expTasks")}
                active={inTaskFlow}
                onClick={openExperimentBrowse}
              />
              <SegBtn
                icon="analytics"
                label={t("experiments.workbench.history")}
                active={screen === "runs" || screen === "detail"}
                onClick={openExperimentRuns}
              />
            </>
          }
        />

        {inTaskFlow ? (
          <ExperimentFlowStrip
            current={
              screen === "configure" ? "configure" : screen === "task" ? "design" : "tasks"
            }
            onBack={
              screen === "configure"
                ? () => openExperimentTask(expTask!)
                : screen === "task"
                  ? openExperimentBrowse
                  : undefined
            }
            onTasks={openExperimentBrowse}
            onDesign={expTask ? () => openExperimentTask(expTask) : undefined}
            onConfigure={expTask ? () => openExperimentConfigure(expTask) : undefined}
          />
        ) : null}

        {screen === "browse" ? (
          <ExperimentTaskBrowser onOpenTask={openExperimentTask} />
        ) : screen === "task" ? (
          <ExperimentTaskDetail
            taskPath={expTask!}
            onConfigure={openExperimentConfigure}
          />
        ) : screen === "configure" ? (
          <ExperimentRunConfigurator
            options={options}
            taskPath={expTask!}
            onLaunched={openExperiment}
          />
        ) : screen === "runs" ? (
          <ExperimentsList onOpen={openExperiment} onNew={openExperimentBrowse} />
        ) : (
          <ExperimentDetail experimentId={experimentId!} onOpenJob={openExperimentJob} />
        )}
      </StudioPageFrame>
    </StudioMeshShell>
  );
}

const FLOW_STEPS = [
  { id: "tasks", label: "Tasks" },
  { id: "design", label: "Design" },
  { id: "configure", label: "Configure" },
] as const;

type FlowStepId = (typeof FLOW_STEPS)[number]["id"];

function ExperimentFlowStrip({
  current,
  onBack,
  onTasks,
  onDesign,
  onConfigure,
}: {
  current: FlowStepId;
  onBack?: () => void;
  onTasks: () => void;
  onDesign?: () => void;
  onConfigure?: () => void;
}) {
  const { t } = useI18n();
  const index = FLOW_STEPS.findIndex((s) => s.id === current);
  const go: Record<FlowStepId, (() => void) | undefined> = {
    tasks: onTasks,
    design: onDesign,
    configure: onConfigure,
  };
  const stepLabels: Record<FlowStepId, string> = {
    tasks: t("experiments.workbench.flow.tasks"),
    design: t("experiments.workbench.flow.design"),
    configure: t("experiments.workbench.flow.configure"),
  };
  return (
    <nav
      aria-label={t("experiments.workbench.flow.ariaLabel")}
      className="mb-2.5 grid shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 rounded-xl border border-outline/30 bg-surface/25 px-2.5 py-1"
    >
      <div className="justify-self-start">
        {onBack ? (
          <button
            type="button"
            onClick={onBack}
            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium text-text-variant hover:bg-surface-high/60 hover:text-text-main ${FOCUS_RING}`}
          >
            <Sym name="arrow_back" size={16} />
            {t("experiments.workbench.back")}
          </button>
        ) : null}
      </div>
      <div className="flex items-center justify-center">
        {FLOW_STEPS.map((step, i) => {
          const active = step.id === current;
          const done = i < index;
          const action = go[step.id];
          const clickable = Boolean(action) && !active;
          return (
            <div key={step.id} className="flex items-center">
              {i > 0 ? (
                <span
                  className={`mx-2 h-px w-10 ${
                    done || active ? "bg-primary/45" : "bg-outline/40"
                  }`}
                  aria-hidden
                />
              ) : null}
              <button
                type="button"
                disabled={!clickable}
                onClick={action}
                aria-current={active ? "step" : undefined}
                className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition ${FOCUS_RING} ${
                  active
                    ? "bg-primary text-on-primary"
                    : clickable
                      ? "text-text-variant hover:bg-surface-high/60 hover:text-text-main"
                      : "cursor-default text-text-dim"
                }`}
              >
                <span
                  className={`grid h-5 w-5 place-items-center rounded-full text-[11px] font-bold ${
                    active
                      ? "bg-on-primary/20"
                      : done
                        ? "bg-primary/15 text-primary"
                        : "bg-surface-high/70"
                  }`}
                >
                  {done ? <Sym name="check" size={13} /> : i + 1}
                </span>
                {stepLabels[step.id]}
              </button>
            </div>
          );
        })}
      </div>
      <div />
    </nav>
  );
}

function Crumb({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`truncate hover:text-text-main ${FOCUS_RING}`}
    >
      {label}
    </button>
  );
}

function SegBtn({
  icon,
  label,
  active,
  onClick,
}: {
  icon: string;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium transition ${FOCUS_RING} ${
        active
          ? "bg-primary text-on-primary"
          : "glass-tile glass-tile--hover text-text-variant hover:text-text-main"
      }`}
    >
      <Sym name={icon} size={16} />
      {label}
    </button>
  );
}
