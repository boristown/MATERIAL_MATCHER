import { ref } from 'vue'

export type WorkspaceStep = 1 | 2 | 3 | 4

export const activeWorkspaceStep = ref<WorkspaceStep | null>(null)

export function setActiveWorkspaceStep(step: WorkspaceStep | null): void {
  activeWorkspaceStep.value = step
}
