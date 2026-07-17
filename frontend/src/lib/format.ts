// Small presentation helpers shared across components.

/** Format a 0..1 relevance score as a whole percentage string. */
export function relevancePercent(score: number): string {
  const clamped = Math.max(0, Math.min(1, score))
  return `${Math.round(clamped * 100)}%`
}

/** Human-readable record date, or an explicit fallback when unavailable. */
export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return 'Date unavailable'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** A readable label for a FHIR resource type. */
export function resourceTypeLabel(resourceType: string): string {
  switch (resourceType) {
    case 'DocumentReference':
      return 'Document'
    case 'DiagnosticReport':
      return 'Diagnostic report'
    default:
      return resourceType
  }
}
