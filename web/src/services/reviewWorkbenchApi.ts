import { api } from '../api'

export type ReviewStatus = 'ALL' | 'MATCHED' | 'REVIEW' | 'CONFIRMED' | 'UNMATCHED'

export type ReviewFilter = {
  status: ReviewStatus
  q?: string
  first_score_min?: number
  first_score_max?: number
}

export type ReviewSelection =
  | { mode: 'explicit'; source_row_ids: string[] }
  | { mode: 'filter'; filter: ReviewFilter }

export type ReviewBatchAction =
  | 'confirm_top1'
  | 'mark_unmatched'
  | 'cancel_manual_match'
  | 'restore_original'

export type ReviewBatchResult = {
  success_count: number
  failed_count: number
  conflict_count: number
  details: Array<{ source_row_id?: string; code?: string; message?: string; type?: string }>
  raw: any
}

function errorStatus(error: any): number {
  return Number(error?.status ?? error?.response?.status ?? 0)
}

function errorCode(error: any): string {
  return String(error?.code ?? error?.response?.data?.error?.code ?? '')
}

function errorMessage(error: any): string {
  return String(error?.message ?? error?.response?.data?.error?.message ?? '操作失败')
}

function toNumber(value: unknown): number {
  const number = Number(value ?? 0)
  return Number.isFinite(number) ? number : 0
}

export function buildWorkbenchParams(
  filter: ReviewFilter,
  page: number,
  pageSize: number,
  includeCandidates = 5,
): Record<string, string | number> {
  const params: Record<string, string | number> = {
    status: filter.status,
    page,
    page_size: pageSize,
    include_candidates: includeCandidates,
  }
  const q = filter.q?.trim()
  if (q) params.q = q
  if (filter.first_score_min !== undefined) params.first_score_min = filter.first_score_min
  if (filter.first_score_max !== undefined) params.first_score_max = filter.first_score_max
  return params
}

export async function fetchWorkbenchPage(taskId: string, filter: ReviewFilter, page: number, pageSize: number): Promise<any> {
  return (await api.get(`/tasks/${taskId}/workbench/items`, {
    params: buildWorkbenchParams(filter, page, pageSize, 5),
  })).data ?? {}
}

export async function fetchCandidates(taskId: string, sourceRowId: string): Promise<any[]> {
  const data = (await api.get(`/tasks/${taskId}/items/${sourceRowId}/candidates`)).data ?? {}
  return Array.isArray(data.candidates) ? data.candidates : []
}

function normalizeBatchResult(data: any): ReviewBatchResult {
  const success = Array.isArray(data?.success) ? data.success.length : toNumber(data?.success_count ?? data?.succeeded)
  const directDetails = Array.isArray(data?.details) ? data.details : []
  const failedDetails = Array.isArray(data?.failed) ? data.failed : []
  const details = [...directDetails, ...failedDetails]
  const conflicts = details.filter(item => String(item?.type ?? '').toLowerCase() === 'conflict' || String(item?.code ?? '').includes('CONFLICT'))
  const failedCount = toNumber(data?.failed_count ?? data?.error_count) || failedDetails.length || details.filter(item => String(item?.type ?? '').toLowerCase() === 'error').length
  const conflictCount = toNumber(data?.conflict_count) || conflicts.length
  return {
    success_count: success,
    failed_count: failedCount,
    conflict_count: conflictCount,
    details,
    raw: data,
  }
}

async function runExplicitRowFallback(taskId: string, action: ReviewBatchAction, sourceRowIds: string[]): Promise<ReviewBatchResult> {
  const details: ReviewBatchResult['details'] = []
  let successCount = 0
  let conflictCount = 0
  const endpoint = action === 'cancel_manual_match' ? 'cancel-match' : 'cancel'

  for (let offset = 0; offset < sourceRowIds.length; offset += 10) {
    const chunk = sourceRowIds.slice(offset, offset + 10)
    const results = await Promise.all(chunk.map(async sourceRowId => {
      try {
        await api.post(`/tasks/${taskId}/items/${sourceRowId}/${endpoint}`, { comment: '' })
        return { ok: true, sourceRowId }
      } catch (error) {
        return { ok: false, sourceRowId, error }
      }
    }))
    for (const result of results) {
      if (result.ok) {
        successCount += 1
        continue
      }
      const code = errorCode(result.error)
      const isConflict = errorStatus(result.error) === 409 || code.includes('CONFLICT')
      if (isConflict) conflictCount += 1
      details.push({
        source_row_id: result.sourceRowId,
        type: isConflict ? 'conflict' : 'error',
        code,
        message: errorMessage(result.error),
      })
    }
  }

  return {
    success_count: successCount,
    failed_count: details.length,
    conflict_count: conflictCount,
    details,
    raw: { success_count: successCount, details },
  }
}

async function postFutureBatch(taskId: string, action: ReviewBatchAction, selection: ReviewSelection): Promise<ReviewBatchResult | null> {
  try {
    const response = await api.post(`/tasks/${taskId}/workbench/batch`, { action, selection })
    return normalizeBatchResult(response.data ?? {})
  } catch (error) {
    if ([404, 405].includes(errorStatus(error))) return null
    throw error
  }
}

export async function runReviewBatch(taskId: string, action: ReviewBatchAction, selection: ReviewSelection): Promise<ReviewBatchResult> {
  if (selection.mode === 'explicit') {
    if (action === 'confirm_top1') {
      const response = await api.post(`/tasks/${taskId}/workbench/batch-confirm-top1`, { source_row_ids: selection.source_row_ids })
      return normalizeBatchResult(response.data ?? {})
    }
    if (action === 'mark_unmatched') {
      const response = await api.post(`/tasks/${taskId}/workbench/batch-reject`, { source_row_ids: selection.source_row_ids })
      return normalizeBatchResult(response.data ?? {})
    }
    return runExplicitRowFallback(taskId, action, selection.source_row_ids)
  }

  const future = await postFutureBatch(taskId, action, selection)
  if (future) return future

  const error = new Error('当前后端尚未合并“按当前筛选批量处理”的 selection contract；本页显式选择仍可正常批量操作。') as Error & { code?: string }
  error.code = 'REVIEW_BATCH_API_PENDING'
  throw error
}

export async function fetchCalibrationStatistics(taskId: string): Promise<any | null> {
  try {
    return (await api.get(`/tasks/${taskId}/calibration`)).data ?? {}
  } catch (error) {
    if ([404, 405].includes(errorStatus(error))) return null
    throw error
  }
}

export async function previewReDecision(taskId: string, successThreshold: number, reviewThreshold: number, mode: 'preview' | 'apply'): Promise<any> {
  return (await api.post(`/tasks/${taskId}/re-decide`, {
    success_threshold: successThreshold,
    review_threshold: reviewThreshold,
    mode,
  })).data ?? {}
}

export function downloadManualWorkbook(taskId: string): void {
  window.location.assign(`/api/tasks/${encodeURIComponent(taskId)}/manual-review.xlsx`)
}

export async function uploadManualWorkbook(taskId: string, file: File): Promise<any> {
  const form = new FormData()
  form.append('file', file)
  return (await api.post(`/tasks/${taskId}/manual-review/import`, form)).data ?? {}
}
