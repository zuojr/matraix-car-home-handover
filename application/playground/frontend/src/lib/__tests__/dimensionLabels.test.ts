import { describe, expect, it } from "vitest";

import { createDimensionLabelLookup } from "../dimensionLabels";
import type { PersonaDimensionLabels } from "../types";

const PACK: PersonaDimensionLabels = {
  locale: "zh-Hans",
  available: true,
  reviewStatus: "machine-assisted",
  dimensions: {
    primary_language: {
      label: "主要语言",
      values: { Mandarin: "普通话", Swahili: "斯瓦希里语" },
    },
    age_bracket: {
      // Values-only entry: label falls back to English.
      values: { "25-34": "25–34岁" },
    },
  },
  taxonomy: {
    background: "背景",
    demographics: "人口统计",
  },
};

describe("createDimensionLabelLookup", () => {
  it("is an inert English passthrough without a pack", () => {
    for (const lookup of [
      createDimensionLabelLookup(null),
      createDimensionLabelLookup(undefined),
      createDimensionLabelLookup({
        locale: "ko",
        available: false,
        dimensions: {},
      }),
    ]) {
      expect(lookup.active).toBe(false);
      expect(lookup.dimLabel("primary_language", "Primary language")).toBe(
        "Primary language",
      );
      expect(lookup.valueLabel("primary_language", "Mandarin")).toBe(
        "Mandarin",
      );
      expect(lookup.taxonomyLabel("background", "Background")).toBe(
        "Background",
      );
    }
  });

  it("returns translated labels and values when the pack has them", () => {
    const lookup = createDimensionLabelLookup(PACK);
    expect(lookup.active).toBe(true);
    expect(lookup.dimLabel("primary_language", "Primary language")).toBe(
      "主要语言",
    );
    expect(lookup.valueLabel("primary_language", "Mandarin")).toBe("普通话");
    expect(lookup.valueLabel("age_bracket", "25-34")).toBe("25–34岁");
    expect(lookup.taxonomyLabel("background", "Background")).toBe("背景");
    expect(lookup.taxonomyLabel("demographics", "Demographics")).toBe(
      "人口统计",
    );
  });

  it("falls back to English for anything untranslated", () => {
    const lookup = createDimensionLabelLookup(PACK);
    // Untranslated value on a translated dimension.
    expect(lookup.valueLabel("primary_language", "Hindi")).toBe("Hindi");
    // Dimension absent from the pack entirely.
    expect(lookup.dimLabel("region", "Region")).toBe("Region");
    expect(lookup.valueLabel("region", "East Asia")).toBe("East Asia");
    // Entry without a label keeps the English label.
    expect(lookup.dimLabel("age_bracket", "Age bracket")).toBe("Age bracket");
    expect(lookup.taxonomyLabel("career", "Career")).toBe("Career");
  });

  it("ignores packs whose dimensions object is empty", () => {
    const lookup = createDimensionLabelLookup({
      locale: "ja",
      available: true,
      dimensions: {},
    });
    expect(lookup.active).toBe(false);
    expect(lookup.dimLabel("primary_language", "Primary language")).toBe(
      "Primary language",
    );
  });
});
