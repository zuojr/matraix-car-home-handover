import { describe, expect, it } from "vitest";

import {
  experimentArmDisplayLabel,
  jobDisplayIdentity,
  parseExperimentArmJob,
} from "../jobDisplay";

describe("parseExperimentArmJob", () => {
  it("groups sibling arms under one experiment id", () => {
    const c0 = parseExperimentArmJob("exp-survey-onboarding-framing-1e9fd26e-c0");
    const c1 = parseExperimentArmJob("exp-survey-onboarding-framing-1e9fd26e-c1");
    expect(c0?.experimentId).toBe("exp-survey-onboarding-framing-1e9fd26e");
    expect(c1?.experimentId).toBe(c0?.experimentId);
    expect(c0?.armIndex).toBe(0);
    expect(c1?.armIndex).toBe(1);
    expect(parseExperimentArmJob("pg-survey-onboarding-framing-aa11bb22")).toBeNull();
  });

  it("parses PUT persona-arm folders (-pN)", () => {
    const p0 = parseExperimentArmJob("exp-survey-trust-ai-abcdef12-p0");
    expect(p0?.experimentId).toBe("exp-survey-trust-ai-abcdef12");
    expect(p0?.armIndex).toBe(0);
  });
});

describe("experimentArmDisplayLabel", () => {
  it("prefers the level label for a single Factor=Level arm", () => {
    expect(
      experimentArmDisplayLabel({
        arm: "Onboarding framing=Feature-framed",
        factorLevels: { context_variant: "feature" },
      }),
    ).toBe("Feature-framed");
  });

  it("keeps multi-factor combinations intact", () => {
    expect(
      experimentArmDisplayLabel({
        arm: "Target URL=Prod · Content=A",
        factorLevels: { target_url: "prod", content_build: "a" },
      }),
    ).toBe("Target URL=Prod · Content=A");
  });

  it("falls back to factor level values", () => {
    expect(
      experimentArmDisplayLabel({
        factorLevels: { framing: "outcome" },
      }),
    ).toBe("outcome");
  });
});

describe("jobDisplayIdentity", () => {
  it("parses experiment arm folders into a title and arm id", () => {
    expect(
      jobDisplayIdentity("exp-survey-onboarding-framing-1e9fd26e-c0"),
    ).toEqual({
      title: "Onboarding Framing",
      shortId: "1e9fd26e-c0",
    });
  });

  it("parses playground single-job folders", () => {
    expect(
      jobDisplayIdentity("pg-survey-onboarding-framing-aa11bb22"),
    ).toEqual({
      title: "Onboarding Framing",
      shortId: "aa11bb22",
    });
  });
});
