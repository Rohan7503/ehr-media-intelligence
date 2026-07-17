// Shared badge treatments. Meaning is carried by the text label; color is only
// a secondary cue, so nothing depends on color alone.

import { resourceTypeLabel } from '../lib/format'

const RESOURCE_STYLES: Record<string, string> = {
  DocumentReference: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
  DiagnosticReport: 'bg-amber-50 text-amber-800 ring-amber-200',
}

export function ResourceTypeBadge({ resourceType }: { resourceType: string }) {
  const style = RESOURCE_STYLES[resourceType] ?? 'bg-slate-100 text-slate-700 ring-slate-200'
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {resourceTypeLabel(resourceType)}
    </span>
  )
}

const CONFIDENCE_STYLES: Record<string, { style: string; label: string }> = {
  low: { style: 'bg-slate-100 text-slate-700 ring-slate-300', label: 'Low confidence' },
  medium: { style: 'bg-sky-50 text-sky-800 ring-sky-200', label: 'Medium confidence' },
  high: { style: 'bg-emerald-50 text-emerald-800 ring-emerald-200', label: 'High confidence' },
}

export function ConfidenceBadge({ confidence }: { confidence: string }) {
  const entry = CONFIDENCE_STYLES[confidence] ?? {
    style: 'bg-slate-100 text-slate-700 ring-slate-300',
    label: `${confidence} confidence`,
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${entry.style}`}
    >
      {entry.label}
    </span>
  )
}
