// Natural-language search input with an explicit submit button. Submits on
// Enter, trims whitespace, refuses empty queries, and disables while loading.

interface SearchBarProps {
  value: string
  loading: boolean
  onChange: (value: string) => void
  onSubmit: () => void
}

function SearchBar({ value, loading, onChange, onSubmit }: SearchBarProps) {
  const canSubmit = value.trim().length > 0 && !loading

  return (
    <form
      className="flex flex-col gap-3 sm:flex-row"
      onSubmit={(event) => {
        event.preventDefault()
        if (canSubmit) {
          onSubmit()
        }
      }}
    >
      <div className="flex-1">
        <label htmlFor="search-query" className="sr-only">
          Search clinical records
        </label>
        <input
          id="search-query"
          type="search"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Search records, e.g. recent abnormal chest imaging"
          autoComplete="off"
          className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus-visible:border-teal-600 focus-visible:ring-2 focus-visible:ring-teal-600/30"
        />
      </div>
      <button
        type="submit"
        disabled={!canSubmit}
        className="inline-flex items-center justify-center rounded-lg bg-teal-700 px-5 py-2.5 font-medium text-white shadow-sm transition-colors hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500"
      >
        {loading ? 'Searching…' : 'Search'}
      </button>
    </form>
  )
}

export default SearchBar
