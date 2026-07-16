function App() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-teal-600 text-sm font-bold text-white">
            EMI
          </span>
          <div>
            <h1 className="text-lg font-semibold">EHR Media Intelligence</h1>
            <p className="text-xs text-slate-500">Clinical document platform</p>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-12">
        <section className="max-w-2xl">
          <h2 className="text-2xl font-semibold tracking-tight">
            Structured insight from unstructured records
          </h2>
          <p className="mt-4 leading-relaxed text-slate-600">
            EHR Media Intelligence ingests synthetic electronic health records,
            normalizes them into FHIR-compatible resources, and makes them
            explorable through AI-generated clinical summaries and semantic
            search.
          </p>
          <p className="mt-4 text-sm text-slate-500">
            The clinician-facing search experience is under construction.
          </p>
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-6 py-4 text-xs text-slate-500">
          Demonstration project using synthetic patient data only. Not intended
          for clinical use.
        </div>
      </footer>
    </div>
  )
}

export default App
