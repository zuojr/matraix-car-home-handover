/**
 * MatrAIx application shell.
 *
 * Routes: Persona World · Task Gallery · Playground · Experiments · Runs.
 * Landing (logo / empty URL) is the MatrAIx home stage.
 */
import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useI18n } from "@/i18n/I18nProvider";
import { TopBar, type StudioMode } from "@/components/TopBar";
import { PlaygroundCockpit } from "@/components/cockpit/PlaygroundCockpit";
import type { PlaygroundTaskType } from "@/components/cockpit/TaskTypeSwitch";
import { HomeView } from "@/components/HomeView";
import { PersonaStoreView } from "@/components/PersonaStoreView";
import { RunsView } from "@/components/RunsView";
import { TaskGalleryView } from "@/components/TaskGalleryView";
import { ExperimentsWorkbench } from "@/components/experiments/ExperimentsWorkbench";
import { AppFooter } from "@/components/AppFooter";

import { api } from "@/lib/api";
import { writePersonaHandoff } from "@/lib/personaHandoffStorage";
import { useUrlState } from "@/lib/useUrlState";
import type { ConfigOptionsResponse, Domain } from "@/lib/types";

function parseMode(value: string | null): StudioMode {
  if (value === "playground") return "playground";
  return "home";
}

/** Drop experiment drill-down keys when the top nav leaves Experiments. */
const LEAVE_EXPERIMENT = {
  expScreen: null,
  expTask: null,
  expConfig: null,
  experimentId: null,
  experimentJob: null,
  experimentTrial: null,
} as const;

export default function App() {
  const { t } = useI18n();
  const { state: urlState, setState: setUrlState } = useUrlState();
  const mode = parseMode(urlState.mode);
  const activeHarborJobId = urlState.harborJob;
  const activeHarborTrialId = urlState.harborTrial;
  const galleryViewActive = urlState.view === "gallery";
  const storeViewActive = urlState.view === "store";
  // Gate only on `view`. Deep-link leftovers (`expTask`, experimentId, …) must
  // not pin the shell on Experiments after the top nav has left that view.
  const experimentsViewActive = urlState.view === "experiments";
  const runsViewActive =
    urlState.view === "runs" ||
    activeHarborJobId !== null ||
    activeHarborTrialId !== null;

  const [, setPlaygroundDomain] = useState<Domain>("movie");

  const optionsQuery = useQuery<ConfigOptionsResponse>({
    queryKey: ["config", "options"],
    queryFn: api.getConfigOptions,
    staleTime: Infinity,
  });

  const openHome = useCallback(() => {
    setUrlState({
      mode: null,
      view: null,
      harborJob: null,
      harborTrial: null,
      ...LEAVE_EXPERIMENT,
    });
  }, [setUrlState]);

  const openTaskGallery = useCallback(() => {
    setUrlState({
      view: "gallery",
      harborJob: null,
      harborTrial: null,
      ...LEAVE_EXPERIMENT,
    });
  }, [setUrlState]);

  const openPersonaStore = useCallback(() => {
    setUrlState({
      view: "store",
      harborJob: null,
      harborTrial: null,
      ...LEAVE_EXPERIMENT,
    });
  }, [setUrlState]);

  const openRunsList = useCallback(() => {
    setUrlState({
      view: "runs",
      harborJob: null,
      harborTrial: null,
      ...LEAVE_EXPERIMENT,
    });
  }, [setUrlState]);

  const openExperiments = useCallback(() => {
    setUrlState({
      view: "experiments",
      expScreen: "browse",
      expTask: null,
      expConfig: null,
      experimentId: null,
      experimentJob: null,
      experimentTrial: null,
      harborJob: null,
      harborTrial: null,
    });
  }, [setUrlState]);

  const openExperimentBrowse = useCallback(() => {
    setUrlState({
      view: "experiments",
      expScreen: "browse",
      expTask: null,
      expConfig: null,
      experimentId: null,
      experimentJob: null,
      experimentTrial: null,
    });
  }, [setUrlState]);

  const openExperimentTask = useCallback(
    (taskPath: string) => {
      setUrlState({
        view: "experiments",
        expScreen: "browse",
        expTask: taskPath,
        expConfig: null,
        experimentId: null,
        experimentJob: null,
        experimentTrial: null,
      });
    },
    [setUrlState],
  );

  const openExperimentConfigure = useCallback(
    (taskPath: string) => {
      setUrlState({
        view: "experiments",
        expScreen: "browse",
        expTask: taskPath,
        expConfig: "1",
        experimentId: null,
        experimentJob: null,
        experimentTrial: null,
      });
    },
    [setUrlState],
  );

  const openExperimentRuns = useCallback(() => {
    setUrlState({
      view: "experiments",
      expScreen: "runs",
      expTask: null,
      expConfig: null,
      experimentId: null,
      experimentJob: null,
      experimentTrial: null,
    });
  }, [setUrlState]);

  const openExperiment = useCallback(
    (experimentId: string) => {
      setUrlState({
        view: "experiments",
        expScreen: "runs",
        expTask: null,
        expConfig: null,
        experimentId,
        experimentJob: null,
        experimentTrial: null,
      });
    },
    [setUrlState],
  );

  const openExperimentJob = useCallback(
    (jobName: string) => {
      setUrlState({ experimentJob: jobName, experimentTrial: null });
    },
    [setUrlState],
  );

  const openExperimentTrial = useCallback(
    (jobName: string, trialName: string) => {
      setUrlState({ experimentJob: jobName, experimentTrial: trialName });
    },
    [setUrlState],
  );

  const backToExperiment = useCallback(() => {
    setUrlState({ experimentJob: null, experimentTrial: null });
  }, [setUrlState]);

  const backToExperimentJob = useCallback(() => {
    setUrlState({ experimentTrial: null });
  }, [setUrlState]);

  const openInPlayground = useCallback(
    (taskType: PlaygroundTaskType, taskId: string) => {
      setUrlState({
        mode: "playground",
        view: null,
        pgTask: taskType,
        pgTaskId: taskId,
        harborJob: null,
        harborTrial: null,
        ...LEAVE_EXPERIMENT,
      });
    },
    [setUrlState],
  );

  const openPersonasInPlayground = useCallback(
    (input: { pool: string; personaIds: string[] }) => {
      writePersonaHandoff(input);
      setUrlState({
        mode: "playground",
        view: null,
        pgPersonaHandoff: "1",
        harborJob: null,
        harborTrial: null,
        ...LEAVE_EXPERIMENT,
      });
    },
    [setUrlState],
  );

  const openHarborJob = useCallback(
    (jobName: string) => {
      setUrlState({ view: "runs", harborJob: jobName, harborTrial: null });
    },
    [setUrlState],
  );

  const openHarborTrial = useCallback(
    (jobName: string, trialName: string) => {
      setUrlState({
        view: "runs",
        harborJob: jobName,
        harborTrial: trialName,
      });
    },
    [setUrlState],
  );

  const backToRunsList = useCallback(() => {
    setUrlState({ view: "runs", harborJob: null, harborTrial: null });
  }, [setUrlState]);

  const backToHarborJob = useCallback(() => {
    setUrlState({ view: "runs", harborTrial: null });
  }, [setUrlState]);

  const closeRunsView = useCallback(() => {
    setUrlState({ view: null, harborJob: null, harborTrial: null });
  }, [setUrlState]);

  const setMode = useCallback(
    (next: StudioMode) => {
      setUrlState({
        mode: next === "home" ? null : next,
        view: null,
        harborJob: null,
        harborTrial: null,
        ...LEAVE_EXPERIMENT,
      });
    },
    [setUrlState],
  );

  const renderTopBar = (variant: "solid" | "glass" = "solid") => (
    <TopBar
      mode={mode}
      onModeChange={setMode}
      runsActive={runsViewActive}
      galleryActive={galleryViewActive}
      storeActive={storeViewActive}
      experimentsActive={experimentsViewActive}
      onOpenHome={openHome}
      onOpenRuns={openRunsList}
      onOpenTaskGallery={openTaskGallery}
      onOpenPersonaStore={openPersonaStore}
      onOpenExperiments={openExperiments}
      variant={variant}
    />
  );
  const topBar = renderTopBar();

  if (galleryViewActive) {
    return (
      <div className="flex h-screen flex-col">
        {topBar}
        <TaskGalleryView
          onOpenInPlayground={openInPlayground}
          onOpenExperimentTask={openExperimentTask}
        />
      </div>
    );
  }

  if (storeViewActive) {
    return (
      <div className="flex h-screen flex-col">
        {topBar}
        <PersonaStoreView onOpenInPlayground={openPersonasInPlayground} />
      </div>
    );
  }

  if (experimentsViewActive) {
    return (
      <div className="flex h-screen flex-col">
        {topBar}
        <ExperimentsWorkbench
          options={optionsQuery.data ?? null}
          experimentId={urlState.experimentId}
          experimentJob={urlState.experimentJob}
          experimentTrial={urlState.experimentTrial}
          expScreen={urlState.expScreen}
          expTask={urlState.expTask}
          expConfig={urlState.expConfig}
          openExperiment={openExperiment}
          openExperimentRuns={openExperimentRuns}
          openExperimentBrowse={openExperimentBrowse}
          openExperimentTask={openExperimentTask}
          openExperimentConfigure={openExperimentConfigure}
          openExperimentJob={openExperimentJob}
          openExperimentTrial={openExperimentTrial}
          backToExperiment={backToExperiment}
          backToExperimentJob={backToExperimentJob}
        />
      </div>
    );
  }

  if (runsViewActive) {
    if (mode === "playground") {
      return (
        <div className="flex h-screen flex-col">
          {topBar}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="hidden min-h-0 flex-1">
              <PlaygroundCockpit
                options={optionsQuery.data ?? null}
                onOpenRuns={openRunsList}
                onOpenHarborJob={openHarborJob}
                onOpenHarborTrial={openHarborTrial}
                onDomainChange={setPlaygroundDomain}
              />
            </div>
            <RunsView
              harborJobId={activeHarborJobId}
              harborTrialId={activeHarborTrialId}
              openHarborJob={openHarborJob}
              openHarborTrial={openHarborTrial}
              backToList={backToRunsList}
              backToHarborJob={backToHarborJob}
              onClose={closeRunsView}
              backLabel={t("runs.backToPlayground")}
            />
          </div>
        </div>
      );
    }

    return (
      <div className="flex h-screen flex-col">
        {topBar}
        <RunsView
          harborJobId={activeHarborJobId}
          harborTrialId={activeHarborTrialId}
          openHarborJob={openHarborJob}
          openHarborTrial={openHarborTrial}
          backToList={backToRunsList}
          backToHarborJob={backToHarborJob}
          onClose={closeRunsView}
          backLabel={t("runs.backHome")}
        />
      </div>
    );
  }

  if (mode === "home") {
    // Home: the stage fills the viewport; top/bottom bars float as glass.
    return (
      <div className="relative flex h-screen flex-col">
        {renderTopBar("glass")}
        <HomeView onOpenPlayground={() => setMode("playground")} />
        <AppFooter context="home" variant="glass" />
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col">
      {topBar}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <PlaygroundCockpit
          options={optionsQuery.data ?? null}
          onOpenRuns={openRunsList}
          onOpenHarborJob={openHarborJob}
          onOpenHarborTrial={openHarborTrial}
          onDomainChange={setPlaygroundDomain}
        />
      </div>
    </div>
  );
}
