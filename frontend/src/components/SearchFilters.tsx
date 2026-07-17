// Resource-type and date-range filters with a clear-filters action. Filters are
// preserved across searches; changing them does not auto-submit.

import type { ResourceType, SearchFilters as Filters } from '../api/types'

interface SearchFiltersProps {
  filters: Filters
  disabled: boolean
  onChange: (filters: Filters) => void
  onClear: () => void
}

const RESOURCE_TYPES: { value: ResourceType | ''; label: string }[] = [
  { value: '', label: 'All resources' },
  { value: 'DocumentReference', label: 'Documents' },
  { value: 'DiagnosticReport', label: 'Diagnostic reports' },
]

const FIELD_CLASS =
  'rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus-visible:border-teal-600 focus-visible:ring-2 focus-visible:ring-teal-600/30'

function SearchFilters({ filters, disabled, onChange, onClear }: SearchFiltersProps) {
  const hasFilters =
    filters.resourceType !== '' || filters.dateFrom !== '' || filters.dateTo !== ''

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="filter-type" className="text-xs font-medium text-slate-600">
          Resource type
        </label>
        <select
          id="filter-type"
          value={filters.resourceType}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...filters, resourceType: event.target.value as ResourceType | '' })
          }
          className={FIELD_CLASS}
        >
          {RESOURCE_TYPES.map((option) => (
            <option key={option.value || 'all'} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="filter-from" className="text-xs font-medium text-slate-600">
          From date
        </label>
        <input
          id="filter-from"
          type="date"
          value={filters.dateFrom}
          disabled={disabled}
          max={filters.dateTo || undefined}
          onChange={(event) => onChange({ ...filters, dateFrom: event.target.value })}
          className={FIELD_CLASS}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="filter-to" className="text-xs font-medium text-slate-600">
          To date
        </label>
        <input
          id="filter-to"
          type="date"
          value={filters.dateTo}
          disabled={disabled}
          min={filters.dateFrom || undefined}
          onChange={(event) => onChange({ ...filters, dateTo: event.target.value })}
          className={FIELD_CLASS}
        />
      </div>

      <button
        type="button"
        onClick={onClear}
        disabled={disabled || !hasFilters}
        className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:text-slate-400"
      >
        Clear filters
      </button>
    </div>
  )
}

export default SearchFilters
