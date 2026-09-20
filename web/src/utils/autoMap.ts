export type AutoMapColumn = {
  header: string
  business_hint?: string | null
}

export type AutoMapCandidate = {
  sourceColumn: AutoMapColumn
  targetColumn: AutoMapColumn
  score: number
}

export const AUTO_MAP_MIN_SCORE = 70
export const AUTO_MAP_AMBIGUITY_MARGIN = 8

export function normalizeAutoMapHeader(value: string): string {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/^(清洗后|清洗前|标准化后|标准化|源侧|目标侧|源|目标)/, '')
    .replace(/[\s_\-—–/（）()【】\[\]:：]+/g, '')
}

export function autoMapPairScore(sourceColumn: AutoMapColumn, targetColumn: AutoMapColumn): number {
  const sourceHeader = normalizeAutoMapHeader(sourceColumn.header)
  const targetHeader = normalizeAutoMapHeader(targetColumn.header)
  if (!sourceHeader || !targetHeader) return 0

  let score = 0
  if (sourceHeader === targetHeader) {
    score = 100
  } else if (sourceHeader.includes(targetHeader) || targetHeader.includes(sourceHeader)) {
    const shorter = Math.min(sourceHeader.length, targetHeader.length)
    const longer = Math.max(sourceHeader.length, targetHeader.length)
    score = 20 + (shorter / Math.max(longer, 1)) * 70
  }

  if (sourceColumn.business_hint && sourceColumn.business_hint === targetColumn.business_hint) {
    score += 20
  }

  return score
}

export function selectOneToOneAutoMapPairs(
  sourceCandidates: AutoMapColumn[],
  targetCandidates: AutoMapColumn[],
): AutoMapCandidate[] {
  const sourceOrder = new Map(sourceCandidates.map((column, index) => [column.header, index]))
  const targetOrder = new Map(targetCandidates.map((column, index) => [column.header, index]))

  const preferredPairs = sourceCandidates.flatMap(sourceColumn => {
    const ranked = targetCandidates
      .map(targetColumn => ({
        sourceColumn,
        targetColumn,
        score: autoMapPairScore(sourceColumn, targetColumn),
      }))
      .filter(item => item.score >= AUTO_MAP_MIN_SCORE)
      .sort((left, right) =>
        right.score - left.score
        || (targetOrder.get(left.targetColumn.header) ?? 0) - (targetOrder.get(right.targetColumn.header) ?? 0),
      )

    const best = ranked[0]
    if (!best) return []

    const runnerUp = ranked[1]
    if (runnerUp && best.score - runnerUp.score < AUTO_MAP_AMBIGUITY_MARGIN) {
      return []
    }

    return [best]
  }).sort((left, right) =>
    right.score - left.score
    || (sourceOrder.get(left.sourceColumn.header) ?? 0) - (sourceOrder.get(right.sourceColumn.header) ?? 0)
    || (targetOrder.get(left.targetColumn.header) ?? 0) - (targetOrder.get(right.targetColumn.header) ?? 0),
  )

  const usedSources = new Set<string>()
  const usedTargets = new Set<string>()
  const selected: AutoMapCandidate[] = []

  for (const item of preferredPairs) {
    if (usedSources.has(item.sourceColumn.header) || usedTargets.has(item.targetColumn.header)) continue
    selected.push(item)
    usedSources.add(item.sourceColumn.header)
    usedTargets.add(item.targetColumn.header)
  }

  return selected
}
