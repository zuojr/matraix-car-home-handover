import { PERSONA_UI_ID_LIST_MAX } from "@/lib/types";

/** Shared fields for POST /api/harbor/jobs persona selection. */
export type PersonaLaunchFields = {
  personaPool: string;
  sampleSize: number;
  personaIds?: string[];
  useEntirePool?: boolean;
  nConcurrentTrials: number;
};

export function resolveCohortSize(input: {
  selectedCount?: number;
  selectedPersonaIds: string[];
}): number {
  return Math.max(input.selectedCount ?? 0, input.selectedPersonaIds.length);
}

export function shouldLaunchEntirePool(input: {
  useEntirePool?: boolean;
  selectedCount?: number;
  selectedPersonaIds: string[];
}): boolean {
  if (input.useEntirePool) return true;
  const size = resolveCohortSize(input);
  if (size <= 0) return false;
  if (size > PERSONA_UI_ID_LIST_MAX) return true;
  return input.selectedPersonaIds.length > 0 && input.selectedPersonaIds.length < size;
}

export function buildPersonaLaunchFields(input: {
  personaPool: string;
  selectedPersonaIds: string[];
  selectedCount?: number;
  useEntirePool?: boolean;
  parallelTrials: number;
}): PersonaLaunchFields {
  const sampleSize = resolveCohortSize(input);
  const entire = shouldLaunchEntirePool(input);
  const nConcurrentTrials = Math.max(1, Math.min(input.parallelTrials, Math.max(sampleSize, 1)));
  if (entire) {
    return {
      personaPool: input.personaPool,
      sampleSize,
      useEntirePool: true,
      nConcurrentTrials,
    };
  }
  return {
    personaPool: input.personaPool,
    sampleSize: input.selectedPersonaIds.length || sampleSize,
    personaIds: input.selectedPersonaIds,
    nConcurrentTrials,
  };
}

export function hasLaunchableCohort(input: {
  selectedCount?: number;
  selectedPersonaIds: string[];
  useEntirePool?: boolean;
}): boolean {
  return resolveCohortSize(input) > 0 || Boolean(input.useEntirePool);
}
