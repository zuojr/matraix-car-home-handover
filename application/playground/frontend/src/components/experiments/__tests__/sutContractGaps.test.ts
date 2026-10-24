import { describe, expect, it } from "vitest";

import type { PersonaPoolCatalog } from "@/lib/types";
import { emptyPersonaDimensionFilters } from "../../cockpit/setup/personaSamplingTypes";
import {
  contractGaps,
  hasContractGaps,
  putEligibilityFilters,
  remainingContractGaps,
  sutCohortReady,
  type SutCohortSpec,
} from "../ExperimentCohortPanel";

function catalogWith(
  dims: { id: string; values: string[] }[],
): PersonaPoolCatalog {
  return {
    pool: "test",
    count: 10,
    dimensionCategories: {
      devProfile: {
        groups: [
          {
            id: "demo",
            label: "Demo",
            dimensionIds: dims.map((d) => d.id),
            dimensions: dims.map((d) => ({
              id: d.id,
              label: d.id,
              values: d.values,
            })),
          },
        ],
      },
    },
  };
}

function baseSpec(patch: Partial<SutCohortSpec> = {}): SutCohortSpec {
  return {
    source: "dataset",
    pool: "test",
    drawMode: "strategy",
    synthMode: "contract",
    perArm: 0,
    perCell: 2,
    allocation: "perCell",
    fields: ["age"],
    seed: 42,
    count: 8,
    genMode: "perCell",
    filters: emptyPersonaDimensionFilters(),
    overlays: [],
    marginals: {},
    ...patch,
  };
}

describe("contractGaps", () => {
  it("reports missing dims and values vs strategy", () => {
    const catalog = catalogWith([{ id: "age", values: ["18-24", "25-34"] }]);
    const gaps = contractGaps(catalog, {
      dimensionFilters: {
        age: ["18-24", "65+"],
        income: ["high"],
      },
      sampling: { fields: ["age", "income"] },
    });
    expect(gaps.missingDims).toEqual(["income"]);
    expect(gaps.missingValues).toEqual([{ dim: "age", values: ["65+"] }]);
    expect(hasContractGaps(gaps)).toBe(true);
  });

  it("is empty when catalog covers the contract", () => {
    const catalog = catalogWith([
      { id: "age", values: ["18-24", "25-34"] },
      { id: "income", values: ["high", "low"] },
    ]);
    const gaps = contractGaps(catalog, {
      dimensionFilters: { age: ["18-24"], income: ["high"] },
      sampling: { fields: ["age", "income"] },
    });
    expect(hasContractGaps(gaps)).toBe(false);
  });

  it("treats overlays as covering missing dims", () => {
    const gaps = {
      missingDims: ["custom_attr"],
      missingValues: [] as { dim: string; values: string[] }[],
    };
    const remaining = remainingContractGaps(gaps, [
      { id: "custom_attr", label: "Custom", values: ["a", "b"] },
    ]);
    expect(hasContractGaps(remaining)).toBe(false);
  });
});

describe("sutCohortReady", () => {
  it("blocks strategy when contract gaps exist", () => {
    expect(sutCohortReady(baseSpec(), { hasContractGaps: true })).toBe(false);
    expect(sutCohortReady(baseSpec(), { hasContractGaps: false })).toBe(true);
  });

  it("requires synthesized pool on generate", () => {
    expect(sutCohortReady(baseSpec({ source: "generate" }))).toBe(false);
    expect(
      sutCohortReady(
        baseSpec({
          source: "generate",
          generatedPool: "gen/x",
          generatedIds: ["p1"],
        }),
      ),
    ).toBe(true);
  });

  it("checks custom mix params", () => {
    expect(
      sutCohortReady(
        baseSpec({ drawMode: "custom", genMode: "random", count: 0, perArm: 0 }),
      ),
    ).toBe(false);
    expect(
      sutCohortReady(
        baseSpec({ drawMode: "custom", genMode: "random", count: 12 }),
      ),
    ).toBe(true);
    expect(
      sutCohortReady(
        baseSpec({
          drawMode: "custom",
          genMode: "perCell",
          fields: [],
          perCell: 2,
          filters: emptyPersonaDimensionFilters(),
        }),
      ),
    ).toBe(false);
    expect(
      sutCohortReady(
        baseSpec({
          drawMode: "custom",
          genMode: "perCell",
          perCell: 2,
          filters: {
            sources: [],
            dimensionFilters: { age: ["18-24", "25-34"] },
          },
        }),
      ),
    ).toBe(true);
  });
});

describe("putEligibilityFilters", () => {
  const extra = {
    sources: [] as string[],
    dimensionFilters: { age_bracket: ["18-24"] },
  };

  it("lets contrast chips override the task-plan values for that dim", () => {
    const out = putEligibilityFilters({
      dimension: "economic_motivation",
      values: ["Cost-sensitive", "Value-driven"],
      synthMode: "contract",
      taskFilters: {
        economic_motivation: ["Cost-sensitive", "Value-driven", "Premium-seeking"],
      },
      extraFilters: emptyPersonaDimensionFilters(),
      overlays: [],
    });
    expect(out.economic_motivation).toEqual(["Cost-sensitive", "Value-driven"]);
  });

  it("keeps extra who on custom and ignores the rest of the task plan", () => {
    const out = putEligibilityFilters({
      dimension: "economic_motivation",
      values: ["Cost-sensitive", "Value-driven"],
      synthMode: "custom",
      taskFilters: {
        economic_motivation: ["Cost-sensitive", "Value-driven", "Premium-seeking"],
        region: ["North America"],
      },
      extraFilters: extra,
      overlays: [],
    });
    expect(out).toEqual({
      age_bracket: ["18-24"],
      economic_motivation: ["Cost-sensitive", "Value-driven"],
    });
  });

  it("ignores extra who on the task plan", () => {
    const out = putEligibilityFilters({
      dimension: "economic_motivation",
      values: ["Indifferent"],
      synthMode: "contract",
      taskFilters: {
        economic_motivation: ["Cost-sensitive", "Indifferent"],
        region: ["North America"],
      },
      extraFilters: extra,
      overlays: [{ id: "study_arm", label: "Study", values: ["a", "b"] }],
    });
    expect(out).toEqual({
      economic_motivation: ["Indifferent"],
      region: ["North America"],
    });
  });
});
