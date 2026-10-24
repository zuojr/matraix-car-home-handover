import { describe, expect, it } from "vitest";

import {
  PERSONA_BENCH_POOL,
  PERSONA_PRODUCTION_1M_POOL,
  type TaskPersonaStrategy,
} from "@/lib/types";

import {
  defaultPersonaSetup,
  hasDurableOperatorCohort,
  keepOperatorCohort,
  resolveTaskHydrateSetup,
  samplingModeForOperatorCohort,
  scrubTaskStrategyFillForCustomMode,
} from "./cockpitPersonaSetupStorage";

const MODEL = "anthropic/claude-haiku-4-5";
const CLARA = "wiki-e690edb701e2";
const FILL_POOL = "persona/datasets/generated-persona-dev-strategy-abc";

const SURVEY_STRATEGY: TaskPersonaStrategy = {
  sampling: {
    mode: "stratified",
    fields: ["economic_motivation"],
    allocation: "proportional",
    sampleSize: 20,
  },
  dimensionFilters: {
    life_stage: ["Parent of young kids"],
  },
};

function storedDraft(
  overrides: Partial<ReturnType<typeof defaultPersonaSetup>> = {},
) {
  return {
    ...defaultPersonaSetup(MODEL),
    ...overrides,
  };
}

describe("samplingModeForOperatorCohort", () => {
  it("matches explicit launch ids instead of strategy stratified-N", () => {
    expect(
      samplingModeForOperatorCohort({
        selectedPersonaIds: [CLARA],
        selectedCount: 1,
      }),
    ).toBe("single");
    expect(
      samplingModeForOperatorCohort({
        selectedPersonaIds: [CLARA, "wiki-other"],
        selectedCount: 2,
      }),
    ).toBe("random");
    expect(
      samplingModeForOperatorCohort({
        selectedPersonaIds: [],
        selectedCount: 20,
        useEntirePool: true,
      }),
    ).toBe("all");
  });
});

describe("hasDurableOperatorCohort", () => {
  it("rejects task-fill generate pools", () => {
    expect(
      hasDurableOperatorCohort({
        personaPool: FILL_POOL,
        selectedPersonaIds: [CLARA],
        selectedCount: 1,
      }),
    ).toBe(false);
  });

  it("accepts a 1M Dataset pick", () => {
    expect(
      hasDurableOperatorCohort({
        personaPool: PERSONA_PRODUCTION_1M_POOL,
        selectedPersonaIds: [CLARA],
        selectedCount: 1,
      }),
    ).toBe(true);
  });
});

describe("resolveTaskHydrateSetup", () => {
  it("keeps Dataset + id together and turns Task default off when picking a survey after a 1M persona", () => {
    const applied = resolveTaskHydrateSetup({
      strategy: SURVEY_STRATEGY,
      stored: storedDraft(),
      hasTaskSpecificStore: false,
      incoming: {
        personaPool: PERSONA_PRODUCTION_1M_POOL,
        selectedPersonaIds: [CLARA],
        selectedCount: 1,
        useEntirePool: false,
      },
      fallbackPersonaModel: MODEL,
    });

    expect(applied.personaPool).toBe(PERSONA_PRODUCTION_1M_POOL);
    expect(applied.selectedPersonaIds).toEqual([CLARA]);
    expect(applied.useTaskDefaultStrategy).toBe(false);
    expect(applied.taskDefaultStrategyDismissed).toBe(true);
    expect(applied.samplingMode).toBe("single");
  });

  it("applies persona_strategy.json on a fresh task with no operator pick", () => {
    const applied = resolveTaskHydrateSetup({
      strategy: SURVEY_STRATEGY,
      stored: storedDraft({
        personaPool: PERSONA_PRODUCTION_1M_POOL,
        selectedPersonaIds: [CLARA],
        selectedCount: 1,
      }),
      hasTaskSpecificStore: false,
      incoming: {
        personaPool: PERSONA_BENCH_POOL,
        selectedPersonaIds: [],
        selectedCount: 0,
        useEntirePool: false,
      },
      fallbackPersonaModel: MODEL,
    });

    expect(applied.useTaskDefaultStrategy).toBe(true);
    expect(applied.selectedPersonaIds).toEqual([]);
    expect(applied.samplingMode).toBe("stratified");
    expect(applied.sampleSize).toBe(20);
    expect(applied.personaPool).toBe(PERSONA_BENCH_POOL);
  });

  it("does not paste leftover ids onto the strategy pool", () => {
    const applied = resolveTaskHydrateSetup({
      strategy: SURVEY_STRATEGY,
      stored: storedDraft({
        personaPool: PERSONA_BENCH_POOL,
        selectedPersonaIds: [CLARA],
        selectedCount: 1,
      }),
      hasTaskSpecificStore: false,
      incoming: {
        personaPool: PERSONA_BENCH_POOL,
        selectedPersonaIds: [],
        selectedCount: 0,
        useEntirePool: false,
      },
      fallbackPersonaModel: MODEL,
    });

    expect(applied.selectedPersonaIds).toEqual([]);
    expect(applied.personaPool).toBe(PERSONA_BENCH_POOL);
    expect(applied.useTaskDefaultStrategy).toBe(true);
  });

  it("restores a dismissed custom 1M pick for the same task", () => {
    const stored = storedDraft({
      personaPool: PERSONA_PRODUCTION_1M_POOL,
      selectedPersonaIds: [CLARA],
      selectedCount: 1,
      useTaskDefaultStrategy: false,
      taskDefaultStrategyDismissed: true,
      samplingMode: "single",
    });
    const applied = resolveTaskHydrateSetup({
      strategy: SURVEY_STRATEGY,
      stored,
      hasTaskSpecificStore: true,
      incoming: {
        personaPool: PERSONA_BENCH_POOL,
        selectedPersonaIds: [],
        selectedCount: 0,
        useEntirePool: false,
      },
      fallbackPersonaModel: MODEL,
    });

    expect(applied.personaPool).toBe(PERSONA_PRODUCTION_1M_POOL);
    expect(applied.selectedPersonaIds).toEqual([CLARA]);
    expect(applied.useTaskDefaultStrategy).toBe(false);
  });

  it("restores this task's fill pool with Task default on", () => {
    const stored = storedDraft({
      personaPool: FILL_POOL,
      selectedPersonaIds: ["gen-1"],
      selectedCount: 1,
      useTaskDefaultStrategy: true,
    });
    const applied = resolveTaskHydrateSetup({
      strategy: SURVEY_STRATEGY,
      stored,
      hasTaskSpecificStore: true,
      incoming: {
        personaPool: FILL_POOL,
        selectedPersonaIds: ["gen-1"],
        selectedCount: 1,
        useEntirePool: false,
      },
      fallbackPersonaModel: MODEL,
    });

    expect(applied.personaPool).toBe(FILL_POOL);
    expect(applied.selectedPersonaIds).toEqual(["gen-1"]);
    expect(applied.useTaskDefaultStrategy).toBe(true);
    expect(applied.samplingMode).toBe("stratified");
  });

  it("does not sticky-restore a fill pool onto the next task", () => {
    const applied = resolveTaskHydrateSetup({
      strategy: SURVEY_STRATEGY,
      stored: storedDraft(),
      hasTaskSpecificStore: false,
      incoming: {
        personaPool: FILL_POOL,
        selectedPersonaIds: ["gen-1"],
        selectedCount: 1,
        useEntirePool: false,
      },
      fallbackPersonaModel: MODEL,
    });

    expect(applied.personaPool).toBe(PERSONA_BENCH_POOL);
    expect(applied.selectedPersonaIds).toEqual([]);
    expect(applied.useTaskDefaultStrategy).toBe(true);
  });
});

describe("scrubTaskStrategyFillForCustomMode", () => {
  it("falls back to the previous non-fill Dataset instead of always bench", () => {
    const scrubbed = scrubTaskStrategyFillForCustomMode(
      storedDraft({
        personaPool: FILL_POOL,
        selectedPersonaIds: ["gen-1"],
        selectedCount: 1,
      }),
      MODEL,
      PERSONA_PRODUCTION_1M_POOL,
    );

    expect(scrubbed.personaPool).toBe(PERSONA_PRODUCTION_1M_POOL);
    expect(scrubbed.selectedPersonaIds).toEqual([]);
    expect(scrubbed.useTaskDefaultStrategy).toBe(false);
  });

  it("leaves a durable Dataset untouched", () => {
    const record = storedDraft({
      personaPool: PERSONA_PRODUCTION_1M_POOL,
      selectedPersonaIds: [CLARA],
      selectedCount: 1,
    });
    expect(scrubTaskStrategyFillForCustomMode(record, MODEL)).toBe(record);
  });
});

describe("keepOperatorCohort", () => {
  it("never pairs leftover ids with a different pool", () => {
    const next = keepOperatorCohort(defaultPersonaSetup(MODEL), {
      personaPool: PERSONA_PRODUCTION_1M_POOL,
      selectedPersonaIds: [CLARA],
      selectedCount: 1,
      useEntirePool: false,
    });
    expect(next.personaPool).toBe(PERSONA_PRODUCTION_1M_POOL);
    expect(next.selectedPersonaIds).toEqual([CLARA]);
    expect(next.useTaskDefaultStrategy).toBe(false);
  });
});
