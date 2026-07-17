// Reusable state display for loading, empty, error, and informational states.
// Meaning is never conveyed by color alone — each variant has an icon glyph and
// descriptive text, and the appropriate ARIA role.

type Tone = 'info' | 'loading' | 'empty' | 'error'

interface StateMessageProps {
  tone: Tone
  title: string
  description?: string
}

const TONE_STYLES: Record<Tone, { container: string; glyph: string; label: string }> = {
  info: { container: 'border-slate-200 bg-white text-slate-600', glyph: 'ℹ', label: 'Information' },
  loading: {
    container: 'border-slate-200 bg-white text-slate-600',
    glyph: '◐',
    label: 'Loading',
  },
  empty: { container: 'border-slate-200 bg-white text-slate-600', glyph: '∅', label: 'No results' },
  error: { container: 'border-rose-200 bg-rose-50 text-rose-800', glyph: '⚠', label: 'Error' },
}

function StateMessage({ tone, title, description }: StateMessageProps) {
  const styles = TONE_STYLES[tone]
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={`flex flex-col items-center gap-2 rounded-xl border px-6 py-12 text-center ${styles.container}`}
    >
      <span
        aria-hidden="true"
        className={`text-2xl ${tone === 'loading' ? 'motion-safe:animate-spin' : ''}`}
      >
        {styles.glyph}
      </span>
      <span className="sr-only">{styles.label}:</span>
      <p className="text-base font-medium text-slate-900">{title}</p>
      {description ? <p className="max-w-md text-sm">{description}</p> : null}
    </div>
  )
}

export default StateMessage
