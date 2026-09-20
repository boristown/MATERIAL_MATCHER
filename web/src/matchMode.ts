export type BusinessMatchMode = 'exact' | 'semantic'

export type MatchModeRule = Record<string, any> & {
  matcher?: string
  __apiMatcher?: string
}

export function businessMatchModeFromApi(value: unknown): BusinessMatchMode {
  return String(value ?? '').trim().toLowerCase() === 'exact' ? 'exact' : 'semantic'
}

export function adaptRuleMatcherFromApi<T extends MatchModeRule>(rule: T): T {
  const apiMatcher = String(rule.matcher ?? 'semantic')
  return {
    ...rule,
    matcher: businessMatchModeFromApi(apiMatcher),
    __apiMatcher: apiMatcher,
  }
}

export function adaptRulesFromApi<T extends MatchModeRule>(rules: T[]): T[] {
  return rules.map(rule => adaptRuleMatcherFromApi(rule))
}

export function setBusinessMatchMode(rule: MatchModeRule, value: unknown): void {
  const businessMode = businessMatchModeFromApi(value)
  rule.matcher = businessMode
  rule.__apiMatcher = businessMode
}

export function adaptRuleMatcherToApi<T extends MatchModeRule>(rule: T): Record<string, unknown> {
  const out: MatchModeRule = { ...rule }
  const businessMode = businessMatchModeFromApi(out.matcher)
  const originalApiMatcher = String(out.__apiMatcher ?? businessMode)

  // Existing published profiles may still contain legacy matcher values
  // (contains/fuzzy/hybrid/numeric). Keep that exact backend value until the
  // user explicitly changes the business-facing selector. New/changed rules
  // are persisted as exact or semantic only.
  out.matcher = businessMatchModeFromApi(originalApiMatcher) === businessMode
    ? originalApiMatcher
    : businessMode
  delete out.__apiMatcher
  return out
}

export function adaptRulesToApi(rules: MatchModeRule[]): Record<string, unknown>[] {
  return rules.map(rule => adaptRuleMatcherToApi(rule))
}
