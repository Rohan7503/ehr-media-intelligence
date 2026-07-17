import { useRef, useState } from 'react'

import { ApiError, search } from './api/client'
import type { SearchFilters as Filters, SearchResultItem } from './api/types'
import PatientDetailDrawer from './components/PatientDetailDrawer'
import SearchBar from './components/SearchBar'
import SearchFiltersPanel from './components/SearchFilters'
import SearchResultCard from './components/SearchResultCard'
import StateMessage from './components/StateMessage'

type SearchStatus = 'initial' | 'loading' | 'results' | 'empty' | 'error'

const EMPTY_FILTERS: Filters = { resourceType: '', dateFrom: '', dateTo: '' }

interface Selection {
  patientId: string
  patientName: string
  trigger: HTMLElement | null
}

function App() {
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [status, setStatus] = useState<SearchStatus>('initial')
  const [results, setResults] = useState<SearchResultItem[]>([])
  const [errorMessage, setErrorMessage] = useState('')
  const [lastQuery, setLastQuery] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [selection, setSelection] = useState<Selection | null>(null)
  const requestRef = useRef<AbortController | null>(null)

  const runSearch = () => {
    const trimmed = query.trim()
    if (!trimmed || status === 'loading') {
      return
    }
    requestRef.current?.abort()
    const controller = new AbortController()
    requestRef.current = controller
    setStatus('loading')
    setErrorMessage('')

    search(trimmed, filters, controller.signal)
      .then((response) => {
        setResults(response.results)
        setElapsed(response.elapsed_ms)
        setLastQuery(response.query)
        setStatus(response.results.length > 0 ? 'results' : 'empty')
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }
        setErrorMessage(
          error instanceof ApiError || error instanceof Error
            ? error.message
            : 'Search failed. Please try again.',
        )
        setStatus('error')
      })
  }

  const openPatient = (result: SearchResultItem, trigger: HTMLElement) => {
    setSelection({ patientId: result.patient_id, patientName: result.patient_name, trigger })
  }

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-teal-700 text-sm font-bold text-white">
            EMI
          </span>
          <div>
            <h1 className="text-lg font-semibold">EHR Media Intelligence</h1>
            <p className="text-xs text-slate-500">
              Semantic search across synthetic clinical records
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
        <section aria-labelledby="search-heading" className="space-y-4">
          <div>
            <h2 id="search-heading" className="text-xl font-semibold tracking-tight">
              Search clinical records
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Enter a natural-language query to find the most relevant document and
              diagnostic records across patients.
            </p>
          </div>
          <SearchBar
            value={query}
            loading={status === 'loading'}
            onChange={setQuery}
            onSubmit={runSearch}
          />
          <SearchFiltersPanel
            filters={filters}
            disabled={status === 'loading'}
            onChange={setFilters}
            onClear={() => setFilters(EMPTY_FILTERS)}
          />
        </section>

        <section aria-labelledby="results-heading" className="mt-8">
          <h2 id="results-heading" className="sr-only">
            Search results
          </h2>
          <p className="sr-only" role="status" aria-live="polite">
            {status === 'loading' ? 'Searching…' : ''}
            {status === 'results'
              ? `${results.length} result${results.length === 1 ? '' : 's'} for ${lastQuery}.`
              : ''}
            {status === 'empty' ? `No results for ${lastQuery}.` : ''}
            {status === 'error' ? `Search error: ${errorMessage}` : ''}
          </p>

          {status === 'initial' ? (
            <StateMessage
              tone="info"
              title="Start a search"
              description="Try a query like “recent abnormal chest imaging” or “fasting lipid panel”."
            />
          ) : null}
          {status === 'loading' ? (
            <StateMessage tone="loading" title="Searching records…" />
          ) : null}
          {status === 'empty' ? (
            <StateMessage
              tone="empty"
              title="No matching records"
              description="No records matched your query and filters. Try broadening the query or clearing filters."
            />
          ) : null}
          {status === 'error' ? (
            <StateMessage tone="error" title="Search failed" description={errorMessage} />
          ) : null}
          {status === 'results' ? (
            <>
              <p className="mb-3 text-xs text-slate-500">
                Top {results.length} result{results.length === 1 ? '' : 's'} · {elapsed.toFixed(0)} ms
              </p>
              <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {results.map((result) => (
                  <li key={result.resource_id}>
                    <SearchResultCard result={result} onOpen={openPatient} />
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-6 py-4 text-xs text-slate-500">
          Demonstration project using synthetic patient data only. AI-generated
          summaries are assistive and are not a clinical decision or a substitute
          for professional review.
        </div>
      </footer>

      {selection ? (
        <PatientDetailDrawer
          key={selection.patientId}
          patientId={selection.patientId}
          patientName={selection.patientName}
          triggerElement={selection.trigger}
          onClose={() => setSelection(null)}
        />
      ) : null}
    </div>
  )
}

export default App
