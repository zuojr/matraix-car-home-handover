import { useI18n } from "@/i18n/I18nProvider";
import type { MessageKey } from "@/i18n/types";

/**
 * Explicit i18n key map — must live in the same file as `t(...)` call sites so
 * `npm run i18n:check` accepts element access (`t(METRIC_DESC_KEYS[k])`).
 */
const METRIC_DESC_KEYS = {
  signup_clicked: "experiments.metric.signup_clicked.desc",
  action_taken: "experiments.metric.action_taken.desc",
  decision_basis: "experiments.metric.decision_basis.desc",
  decision_reason: "experiments.metric.decision_reason.desc",
  exploration_style: "experiments.metric.exploration_style.desc",
  chosen_option: "experiments.metric.chosen_option.desc",
  overall_experience_rating: "experiments.metric.overall_experience_rating.desc",
  effort_rating: "experiments.metric.effort_rating.desc",
  trust_level: "experiments.metric.trust_level.desc",
  need_constraint_satisfaction: "experiments.metric.need_constraint_satisfaction.desc",
  personal_preference_satisfaction: "experiments.metric.personal_preference_satisfaction.desc",
  clarity_of_next_step: "experiments.metric.clarity_of_next_step.desc",
  feedback_reason: "experiments.metric.feedback_reason.desc",
} as const satisfies Record<string, MessageKey>;

type MetricDescKey = keyof typeof METRIC_DESC_KEYS;

export function isMetricDescKey(key: string): key is MetricDescKey {
  return key in METRIC_DESC_KEYS;
}

/** Translated metric description, or null when the metric has no catalogued copy. */
export function useMetricDescription(metricKey: string): string | null {
  const { t } = useI18n();
  if (!isMetricDescKey(metricKey)) return null;
  return t(METRIC_DESC_KEYS[metricKey]);
}

/** Same lookup without a hook — for call sites that already have `t`. */
export function translateMetricDescription(
  t: (key: MessageKey) => string,
  metricKey: string,
): string | null {
  if (!isMetricDescKey(metricKey)) return null;
  return t(METRIC_DESC_KEYS[metricKey]);
}
