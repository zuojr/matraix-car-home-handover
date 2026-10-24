import { TaskGalleryContent } from "./TaskGalleryContent";
import type { PlaygroundTaskType } from "./cockpit/TaskTypeSwitch";
import {
  StudioMeshShell,
  StudioPageFrame,
  StudioPageHeader,
} from "./studio/StudioShell";
import { useI18n } from "@/i18n/I18nProvider";

export interface TaskGalleryViewProps {
  onOpenInPlayground: (taskType: PlaygroundTaskType, taskId: string) => void;
  onOpenExperimentTask: (taskPath: string) => void;
}

export function TaskGalleryView({
  onOpenInPlayground,
  onOpenExperimentTask,
}: TaskGalleryViewProps) {
  const { t } = useI18n();

  return (
    <StudioMeshShell>
      <StudioPageFrame fill>
        <StudioPageHeader
          eyebrow={t("catalog.taskGallery.eyebrow")}
          title={t("catalog.taskGallery.title")}
          subtitle={t("catalog.taskGallery.subtitle")}
        />
        <TaskGalleryContent
          onOpenInPlayground={onOpenInPlayground}
          onOpenExperimentTask={onOpenExperimentTask}
          autoFocusSearch
        />
      </StudioPageFrame>
    </StudioMeshShell>
  );
}

export default TaskGalleryView;
