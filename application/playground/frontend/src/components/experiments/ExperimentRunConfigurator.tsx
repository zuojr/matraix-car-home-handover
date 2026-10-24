import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useI18n } from "@/i18n/I18nProvider";
import type {
  ConfigOptionsResponse,
  ExperimentAxis,
  ExperimentTaskDetail as TaskDetail,
  PersonaPoolCatalog,
} from "@/lib/types";
import {
  cuaRuntimeOptionsForPlatform,
  defaultWebPersonaAgentForFamily,
  personaModelProviderLabel,
  suggestedCuaBackend,
  suggestedWebPersonaAgent,
  webAgentFamily,
  webPersonaAgentsForFamily,
  type PersonaAgentOption,
  type WebAgentFamily,
} from "@/lib/personaAgentCatalog";
import { FOCUS_RING, Sym } from "../cockpit/cockpitShared";
import { CockpitInlineCount } from "../cockpit/setup/CockpitCountField";
import { CockpitSelect, type CockpitSelectOption } from "../cockpit/setup/CockpitSelect";
import { StudioGlassPanel } from "../studio/StudioShell";
import {
  AXIS_META,
  LAUNCH_CTA_CLASS,
  MetaChip,
  SectionHeader,
  designLabel,
  errMessage,
} from "./experimentShared";
import {
  PutCohortPanel,
  SutCohortPanel,
  contractGaps,
  defaultPutSpec,
  defaultSutSpec,
  flattenFilters,
  hasContractGaps,
  mixAxesFromWho,
  putCohortReady,
  putDimensionId,
  sutCohortReady,
  type PutCohortSpec,
  type SutCohortSpec,
} from "./ExperimentCohortPanel";

export interface ExperimentRunConfiguratorProps {
  options: ConfigOptionsResponse | null;
  taskPath: string;
  onLaunched: (id: string) => void;
}

/** Resolve the one SUT cohort into launch fields, sampling on the client when needed. */
async function resolveSutFields(
  spec: SutCohortSpec,
  taskPath: string,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (spec.source === "generate") {
    if (!spec.generatedPool || !spec.generatedIds?.length) {
      throw new Error(t("experiments.configurator.errors.synthesizeFirst"));
    }
    return { personaPool: spec.generatedPool, personaIds: spec.generatedIds };
  }
  if (spec.drawMode === "strategy") {
    return {
      personaPool: spec.pool || undefined,
      perArm: spec.perArm > 0 ? spec.perArm : undefined,
    };
  }
  // custom mix → sample API (axes = dims with selected values in Who)
  const dimensionFilters = flattenFilters(spec.filters);
  const hasFilters = Object.keys(dimensionFilters).length > 0;
  const axes = mixAxesFromWho(spec.filters, spec.overlays);
  const sampleSize = spec.count > 0 ? spec.count : spec.perArm;
  const result = await api.samplePersonaPool({
    pool: spec.pool || undefined,
    taskPath,
    seed: spec.seed,
    ...(hasFilters ? { dimensionFilters } : {}),
    ...(spec.filters.sources.length > 0 ? { sources: spec.filters.sources } : {}),
    ...(spec.genMode === "random"
      ? { sampleSize }
      : spec.genMode === "perCell"
        ? { fields: axes, perCell: spec.perCell, allocation: "perCell" }
        : {
            fields: axes,
            sampleSize: spec.count,
            allocation: "proportional",
          }),
  });
  if (result.personaIds.length === 0) {
    throw new Error(t("experiments.configurator.errors.samplingEmpty"));
  }
  return { personaPool: result.pool ?? spec.pool, personaIds: result.personaIds };
}

function cohortSizeForParallelCap(
  axis: ExperimentAxis,
  sut: SutCohortSpec | null,
  put: PutCohortSpec | null,
): number {
  if (axis === "put") {
    const sizes = (put?.arms ?? []).map((a) => a.personaIds?.length ?? 0);
    const ready = sizes.filter((n) => n > 0);
    if (ready.length > 0) return Math.max(1, ...ready);
    return Math.max(1, put?.perArm || put?.count || 1);
  }
  if (!sut) return 100;
  if (sut.source === "generate") {
    if (sut.generatedIds?.length) return Math.max(1, sut.generatedIds.length);
    return Math.max(1, sut.count || sut.perArm || 1);
  }
  if (sut.drawMode === "strategy") {
    return Math.max(1, sut.perArm || 256);
  }
  if (sut.genMode === "random") {
    return Math.max(1, sut.count || sut.perArm || 1);
  }
  if (sut.genMode === "proportional") {
    return Math.max(1, sut.count || 1);
  }
  // by cell
  const flat = flattenFilters(sut.filters);
  const fields = sut.fields.length > 0 ? sut.fields : Object.keys(flat);
  const cells = Math.max(
    1,
    fields.reduce((n, f) => n * Math.max(1, (flat[f] ?? []).length), 1),
  );
  return Math.max(1, cells * (sut.perCell || 1));
}

export function ExperimentRunConfigurator({
  options,
  taskPath,
  onLaunched,
}: ExperimentRunConfiguratorProps) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const AGENT_FAMILIES: { id: WebAgentFamily; label: string; hint: string }[] = [
    {
      id: "browser",
      label: t("experiments.configurator.family.browser"),
      hint: t("experiments.configurator.family.browserHint"),
    },
    {
      id: "cli",
      label: t("experiments.configurator.family.cli"),
      hint: t("experiments.configurator.family.cliHint"),
    },
  ];
  const [name, setName] = useState("");
  const [parallelTrials, setParallelTrials] = useState(2);
  const [parallelArms, setParallelArms] = useState(true);

  const taskQuery = useQuery<TaskDetail>({
    queryKey: ["experiment-task", taskPath],
    queryFn: () => api.getExperimentTask(taskPath),
    retry: false,
  });
  const detail = taskQuery.data;
  const axis: ExperimentAxis = detail?.axis === "put" ? "put" : "sut";

  const [sut, setSut] = useState<SutCohortSpec | null>(null);
  const sutSpec = sut ?? (detail ? defaultSutSpec(detail) : null);

  const [put, setPut] = useState<PutCohortSpec | null>(null);
  const putSpec = put ?? (detail ? defaultPutSpec(detail) : null);

  // A PUT experiment's arms are its contrast values (built or selected), not the
  // factorial design cells — those describe the single baseline grid.
  const armCount =
    axis === "put"
      ? putSpec?.arms?.length || putSpec?.values?.length || 0
      : detail?.design.cells.length ?? 0;

  const sutCatalogQuery = useQuery<PersonaPoolCatalog>({
    queryKey: ["persona-pool-catalog", sutSpec?.pool],
    queryFn: () => api.getPersonaPoolCatalog(sutSpec?.pool || undefined),
    enabled:
      Boolean(sutSpec) &&
      sutSpec!.source === "dataset" &&
      sutSpec!.drawMode === "strategy" &&
      Boolean(sutSpec!.pool),
    staleTime: 60_000,
  });
  const sutHasContractGaps = useMemo(() => {
    if (!sutSpec || !detail || sutSpec.source !== "dataset" || sutSpec.drawMode !== "strategy") {
      return false;
    }
    if (!sutSpec.pool) return false;
    // Block Task default while coverage is unknown or known-incomplete.
    if (sutCatalogQuery.isPending || sutCatalogQuery.isFetching) {
      if (!sutCatalogQuery.data) return true;
    }
    if (!sutCatalogQuery.data) return false;
    return hasContractGaps(contractGaps(sutCatalogQuery.data, detail.cohortStrategy));
  }, [
    sutSpec,
    detail,
    sutCatalogQuery.data,
    sutCatalogQuery.isPending,
    sutCatalogQuery.isFetching,
  ]);

  const personaModelKnob = options?.knobs.find((k) => k.key === "personaModel");
  const personaModelOptions = personaModelKnob?.options ?? [];
  const defaultPersonaModel =
    (options?.defaults?.personaModel as string | undefined) ||
    options?.environment?.personaModel ||
    "";
  const [personaModel, setPersonaModel] = useState<string>("");
  const activePersonaModel = personaModel || defaultPersonaModel;

  // Web/os-app persona agent harness — per-run operator choice (like the model).
  const appType = detail?.appType ?? null;
  const taskBasename = taskPath.split("/").filter(Boolean).pop() ?? taskPath;
  const [webAgent, setWebAgent] = useState<string>("");
  const activeWebAgent = webAgent || suggestedWebPersonaAgent(taskBasename);
  const webFamily = webAgentFamily(activeWebAgent);
  const harnessOptions = useMemo<PersonaAgentOption[]>(
    () => webPersonaAgentsForFamily(webFamily),
    [webFamily],
  );
  const osPlatform = detail?.platform ?? "linux";
  const [cuaBackend, setCuaBackend] = useState<string>("");
  const activeCuaBackend =
    cuaBackend || detail?.osAppBackend || suggestedCuaBackend(osPlatform);
  const runtimeOptions = useMemo<PersonaAgentOption[]>(
    () => cuaRuntimeOptionsForPlatform(osPlatform),
    [osPlatform],
  );
  const harnessSelectOptions = useMemo<CockpitSelectOption[]>(
    () => harnessOptions.map((o) => ({ value: o.value, label: o.label, meta: o.capability })),
    [harnessOptions],
  );
  const runtimeSelectOptions = useMemo<CockpitSelectOption[]>(
    () => runtimeOptions.map((o) => ({ value: o.value, label: o.label, meta: o.capability })),
    [runtimeOptions],
  );
  const changeWebFamily = (next: WebAgentFamily) => {
    if (next === webFamily) return;
    setWebAgent(defaultWebPersonaAgentForFamily(next, taskBasename));
  };
  const showAgentPanel = appType === "web" || appType === "os-app";

  const parallelMax = cohortSizeForParallelCap(axis, sutSpec, putSpec);
  const parallelValue = Math.min(Math.max(1, parallelTrials), parallelMax);
  const effectiveConcurrent = parallelValue * (parallelArms ? Math.max(1, armCount) : 1);

  const createMutation = useMutation({
    mutationFn: async () => {
      const execution = {
        nConcurrentTrials: parallelValue,
        parallelArms,
      };
      const agentFields =
        appType === "os-app"
          ? { cuaBackend: activeCuaBackend }
          : appType === "web"
            ? { agentName: activeWebAgent }
            : {};
      if (axis === "put") {
        if (!putSpec || !putCohortReady(putSpec)) {
          throw new Error(t("experiments.configurator.errors.drawContrastFirst"));
        }
        return api.createExperiment({
          taskPath,
          axis: "put",
          putDimension: putDimensionId(detail!),
          putArms: putSpec.arms,
          name: name.trim() || undefined,
          seed: putSpec.seed,
          personaModel: activePersonaModel || undefined,
          ...agentFields,
          ...execution,
        });
      }
      const fields = await resolveSutFields(sutSpec!, taskPath, t);
      return api.createExperiment({
        taskPath,
        axis: "sut",
        name: name.trim() || undefined,
        seed: sutSpec!.seed,
        personaModel: activePersonaModel || undefined,
        ...agentFields,
        ...fields,
        ...execution,
      });
    },
    onSuccess: (manifest) => {
      qc.invalidateQueries({ queryKey: ["experiments"] });
      onLaunched(manifest.experimentId);
    },
  });

  const meta = AXIS_META[axis];

  const modelSelectOptions = useMemo<CockpitSelectOption[]>(() => {
    return personaModelOptions.map((o) => ({
      value: o.value,
      label: o.value === defaultPersonaModel ? `${o.label} · default` : o.label,
      group: personaModelProviderLabel(o.value),
    }));
  }, [personaModelOptions, defaultPersonaModel]);

  if (taskQuery.isLoading || !sutSpec || !putSpec) {
    return <p className="text-[13px] text-text-dim">{t("experiments.configurator.loadingTask")}</p>;
  }
  if (taskQuery.isError || !detail) {
    return (
      <p className="rounded-md bg-danger/10 p-3 text-[13px] text-danger" role="alert">
        {errMessage(taskQuery.error)}
      </p>
    );
  }

  const cohortOk =
    axis === "put"
      ? putCohortReady(putSpec)
      : sutCohortReady(sutSpec, { hasContractGaps: sutHasContractGaps }) && armCount > 0;
  const launchDisabled = createMutation.isPending || !cohortOk;
  const launchLabel =
    axis === "put"
      ? t("experiments.configurator.launchContrast", { count: putSpec.arms?.length || 0 })
      : t("experiments.configurator.launchExperiment", { count: armCount });

  return (
    <div className="flex flex-col gap-2.5 pb-1">
      <StudioGlassPanel className="overflow-visible px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span
            className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] font-bold ${
              axis === "put" ? "bg-secondary/14 text-secondary" : "bg-primary/14 text-primary"
            }`}
            title={meta.blurb}
          >
            <Sym name={meta.icon} size={14} />
            {meta.code}
          </span>
          <span className="min-w-0 truncate text-[14px] font-semibold text-text-main">
            {detail.name}
          </span>
          <MetaChip>{detail.appType ?? "?"}</MetaChip>
          <MetaChip>{designLabel(detail.declaredDesignType, t)}</MetaChip>
          <MetaChip>{t("experiments.configurator.arms", { count: armCount })}</MetaChip>
        </div>

        <div className="mt-3 flex flex-col gap-2.5">
          {/* The brain: which LLM powers the persona. */}
          <div>
            {modelSelectOptions.length === 0 ? (
              <>
                <span className="mb-1.5 block text-[13px] font-medium text-text-dim">
                  {t("experiments.configurator.personaModel")}
                </span>
                <p className="rounded-lg border border-outline/30 bg-surface/40 px-3 py-2 text-[12.5px] text-text-variant">
                  {activePersonaModel || t("experiments.configurator.workspaceDefault")}
                </p>
              </>
            ) : (
              <CockpitSelect
                label={t("experiments.configurator.personaModel")}
                value={activePersonaModel}
                options={modelSelectOptions}
                onChange={setPersonaModel}
                wideMenu
                showSelectedMeta={false}
              />
            )}
          </div>

          {/* The body: how the persona drives the app (harness / runtime) — kept to one row. */}
          {showAgentPanel ? (
            <div className="border-t border-outline/20 pt-2.5">
              <div className="mb-1.5 flex items-center gap-1.5">
                <Sym name="smart_toy" size={14} className="text-primary" />
                <span className="text-[13px] font-medium text-text-dim">{t("experiments.configurator.agent")}</span>
                <span className="text-[11.5px] text-text-dim">
                  ·{" "}
                  {appType === "os-app"
                    ? t("experiments.configurator.agentComputerUse", { platform: osPlatform })
                    : t("experiments.configurator.agentDrivesSite")}
                </span>
              </div>
              {appType === "web" ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 gap-0.5 rounded-lg bg-surface-lowest/80 p-0.5">
                    {AGENT_FAMILIES.map((fam) => {
                      const active = webFamily === fam.id;
                      return (
                        <button
                          key={fam.id}
                          type="button"
                          aria-pressed={active}
                          disabled={createMutation.isPending}
                          onClick={() => changeWebFamily(fam.id)}
                          title={fam.hint}
                          className={`rounded-md px-2 py-1.5 text-[12px] font-medium transition disabled:opacity-55 ${FOCUS_RING} ${
                            active
                              ? "bg-primary text-on-primary"
                              : "text-text-variant hover:bg-surface-high/50 hover:text-text-main"
                          }`}
                        >
                          {fam.label}
                        </button>
                      );
                    })}
                  </div>
                  <CockpitSelect
                    label={t("experiments.configurator.harness")}
                    value={activeWebAgent}
                    options={harnessSelectOptions}
                    onChange={setWebAgent}
                    disabled={createMutation.isPending}
                    wideMenu
                    metaOnRight
                  />
                </div>
              ) : (
                <CockpitSelect
                  label={t("experiments.configurator.runtime")}
                  value={activeCuaBackend}
                  options={runtimeSelectOptions}
                  onChange={setCuaBackend}
                  disabled={createMutation.isPending}
                  wideMenu
                  metaOnRight
                />
              )}
              {appType === "web" && webFamily === "cli" ? (
                <p className="mt-1.5 flex items-center gap-1 text-[11px] text-warn">
                  <Sym name="warning" size={12} />
                  {t("experiments.configurator.cliWebWarning")}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </StudioGlassPanel>

      {/* Full cohort content — no inner scroll; page scrolls only if content grows. */}
      <StudioGlassPanel className="overflow-visible p-3">
        <SectionHeader
          icon="groups"
          title={
            axis === "put"
              ? t("experiments.configurator.contrastCohorts")
              : t("experiments.configurator.cohort")
          }
          hint={
            axis === "put"
              ? undefined
              : t("experiments.configurator.armsPairedHint", { count: armCount })
          }
        />
        {axis === "put" ? (
          <PutCohortPanel detail={detail} value={putSpec} onChange={setPut} />
        ) : (
          <SutCohortPanel
            detail={detail}
            value={sutSpec}
            onChange={setSut}
          />
        )}
      </StudioGlassPanel>

      <StudioGlassPanel className="sticky bottom-0 z-20 overflow-visible border border-outline/35 bg-surface/90 px-4 py-2.5 backdrop-blur-md supports-[backdrop-filter]:bg-surface/75">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <CockpitInlineCount
            label={t("experiments.configurator.parallel")}
            value={parallelValue}
            onChange={setParallelTrials}
            min={1}
            max={parallelMax}
            disabled={createMutation.isPending}
          />
          <label
            className={`inline-flex cursor-pointer items-center gap-2 text-[13px] ${
              createMutation.isPending ? "opacity-50" : ""
            }`}
          >
            <input
              type="checkbox"
              checked={parallelArms}
              disabled={createMutation.isPending || armCount < 2}
              onChange={(e) => setParallelArms(e.target.checked)}
              className="h-3.5 w-3.5 accent-primary"
            />
            <span className="text-text-variant">{t("experiments.configurator.parallelArms")}</span>
          </label>
          <MetaChip tone="secondary">
            {t("experiments.configurator.concurrent", { count: effectiveConcurrent })}
            {parallelArms && armCount > 1 ? ` · ${parallelValue}×${armCount}` : ""}
          </MetaChip>
        </div>
        <div className="mt-2.5 flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-[200px] max-w-sm flex-1">
            <label className="mb-1 block text-[12px] text-text-dim">{t("experiments.configurator.name")}</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={detail.name}
              className={`w-full rounded-md border border-outline/40 bg-field/60 px-2 py-1.5 text-[13px] text-text-main ${FOCUS_RING}`}
            />
          </div>
          <button
            type="button"
            disabled={launchDisabled}
            onClick={() => createMutation.mutate()}
            className={`${LAUNCH_CTA_CLASS} ${FOCUS_RING}`}
          >
            <Sym name="rocket_launch" fill={1} size={18} />
            {createMutation.isPending ? t("experiments.configurator.launching") : launchLabel}
          </button>
        </div>
        {createMutation.isError ? (
          <p className="mt-2 rounded-md bg-danger/10 p-2 text-[12px] text-danger" role="alert">
            {errMessage(createMutation.error)}
          </p>
        ) : null}
      </StudioGlassPanel>
    </div>
  );
}
