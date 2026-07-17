// A ranked search result. The whole card is a keyboard-operable button that
// opens the patient detail drawer (Enter or Space).

import type { SearchResultItem } from '../api/types'
import { formatDate, relevancePercent } from '../lib/format'
import { ResourceTypeBadge } from './Badge'

interface SearchResultCardProps {
  result: SearchResultItem
  onOpen: (result: SearchResultItem, trigger: HTMLElement) => void
}

function SearchResultCard({ result, onOpen }: SearchResultCardProps) {
  const percent = relevancePercent(result.relevance_score)

  const open = (event: { currentTarget: HTMLElement }) => {
    onOpen(result, event.currentTarget)
  }

  return (
    <article
      role="button"
      tabIndex={0}
      aria-label={`Open patient detail for ${result.patient_name}, ${result.title}, relevance ${percent}`}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          open(event)
        }
      }}
      className="cursor-pointer rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900">{result.patient_name}</h3>
          <p className="text-sm text-slate-500">MRN {result.mrn}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <ResourceTypeBadge resourceType={result.resource_type} />
          <span className="text-xs text-slate-500">
            <span aria-hidden="true">{percent} match</span>
            <span className="sr-only">
              Relevance {percent} ({result.relevance_score.toFixed(3)})
            </span>
          </span>
        </div>
      </div>

      <div className="mt-4">
        <p className="text-sm font-medium text-slate-900">{result.title}</p>
        <p className="text-xs text-slate-500">{formatDate(result.record_date)}</p>
        <p className="mt-2 line-clamp-3 text-sm text-slate-600">{result.resource_text_snippet}</p>
      </div>

      {result.clinical_summary_snippet ? (
        <div className="mt-4 rounded-lg border border-slate-100 bg-slate-50 p-3">
          <p className="text-xs font-medium text-slate-500">Cached summary</p>
          <p className="mt-1 line-clamp-2 text-sm text-slate-600">
            {result.clinical_summary_snippet}
          </p>
        </div>
      ) : null}
    </article>
  )
}

export default SearchResultCard
