// Accessible patient detail panel: a right-side drawer on desktop and a
// full-screen modal panel on small screens. Uses dialog semantics, traps focus,
// closes on Escape or backdrop click, restores focus to the triggering element,
// and prevents background interaction while open. It fetches the detail itself
// and never displays raw FHIR JSON or base64.

import { useEffect, useRef, useState } from 'react'

import { ApiError, getPatient } from '../api/client'
import type { LinkedResource, PatientDetail } from '../api/types'
import { formatDate } from '../lib/format'
import { ConfidenceBadge, ResourceTypeBadge } from './Badge'
import StateMessage from './StateMessage'

interface PatientDetailDrawerProps {
  patientId: string
  patientName: string
  triggerElement: HTMLElement | null
  onClose: () => void
}

type Status = 'loading' | 'loaded' | 'notFound' | 'error'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea, [tabindex]:not([tabindex="-1"])'

function PatientDetailDrawer({
  patientId,
  patientName,
  triggerElement,
  onClose,
}: PatientDetailDrawerProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [detail, setDetail] = useState<PatientDetail | null>(null)
  const [errorMessage, setErrorMessage] = useState('')

  // Fetch the detail; cancel on unmount. The component is keyed by patientId in
  // the parent, so it remounts (resetting to the 'loading' initial state) when
  // a different patient is opened.
  useEffect(() => {
    const controller = new AbortController()
    getPatient(patientId, controller.signal)
      .then((data) => {
        setDetail(data)
        setStatus('loaded')
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }
        if (error instanceof ApiError && error.status === 404) {
          setStatus('notFound')
          return
        }
        setErrorMessage(error instanceof Error ? error.message : 'Something went wrong.')
        setStatus('error')
      })
    return () => controller.abort()
  }, [patientId])

  // Lock background scroll while open.
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  // Move focus into the drawer on open; restore it to the trigger on close.
  useEffect(() => {
    closeButtonRef.current?.focus()
    return () => {
      triggerElement?.focus()
    }
  }, [triggerElement])

  // Escape to close and a simple focus trap.
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab' || !dialogRef.current) {
      return
    }
    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
    ).filter((element) => element.offsetParent !== null)
    if (focusable.length === 0) {
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const active = document.activeElement
    if (event.shiftKey && active === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const titleId = 'patient-detail-title'

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-slate-900/40 motion-safe:transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKeyDown}
        className="relative flex h-full w-full flex-col overflow-y-auto bg-white shadow-xl sm:max-w-lg"
      >
        <header className="sticky top-0 flex items-start justify-between gap-4 border-b border-slate-200 bg-white px-6 py-4">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-900">
              {detail?.patient_name || patientName}
            </h2>
            {detail ? <p className="text-sm text-slate-500">MRN {detail.mrn}</p> : null}
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close patient detail"
            className="rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ✕
            </span>
          </button>
        </header>

        <div className="flex-1 px-6 py-5">
          {status === 'loading' ? (
            <StateMessage tone="loading" title="Loading patient detail…" />
          ) : null}
          {status === 'notFound' ? (
            <StateMessage
              tone="empty"
              title="Patient not found"
              description="This patient is no longer available in the index."
            />
          ) : null}
          {status === 'error' ? (
            <StateMessage tone="error" title="Could not load patient detail" description={errorMessage} />
          ) : null}
          {status === 'loaded' && detail ? <DetailBody detail={detail} /> : null}
        </div>
      </div>
    </div>
  )
}

function DetailBody({ detail }: { detail: PatientDetail }) {
  return (
    <div className="space-y-6">
      <section aria-labelledby="demographics-heading">
        <h3 id="demographics-heading" className="text-sm font-semibold text-slate-900">
          Demographics
        </h3>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <Demographic label="Date of birth" value={formatMaybe(detail.date_of_birth)} />
          <Demographic label="Gender" value={formatMaybe(capitalize(detail.gender))} />
          <Demographic
            label="Bundle status"
            value={detail.bundle_valid ? 'Valid' : 'Invalid'}
          />
        </dl>
      </section>

      <section aria-labelledby="summary-heading">
        <h3 id="summary-heading" className="text-sm font-semibold text-slate-900">
          Clinical summary
        </h3>
        {detail.summary ? (
          <div className="mt-2 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <ConfidenceBadge confidence={detail.summary.confidence} />
            <SummaryField label="Chief concern" values={[detail.summary.chief_concern]} />
            <SummaryField label="Key diagnoses" values={detail.summary.key_diagnoses} />
            <SummaryField
              label="Recent imaging / lab / media"
              values={detail.summary.recent_media_records}
            />
            <SummaryField label="Flagged anomalies" values={detail.summary.flagged_anomalies} />
            <p className="border-t border-slate-200 pt-3 text-xs italic text-slate-500">
              {detail.summary.disclaimer}
            </p>
          </div>
        ) : (
          <p className="mt-2 rounded-lg border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-500">
            No cached summary is available for this patient yet. Summaries appear
            here only after they have been generated by the summarization pipeline.
          </p>
        )}
      </section>

      <section aria-labelledby="resources-heading">
        <h3 id="resources-heading" className="text-sm font-semibold text-slate-900">
          Linked FHIR resources ({detail.resources.length})
        </h3>
        <ul className="mt-2 space-y-3">
          {detail.resources.map((resource) => (
            <li key={resource.resource_id}>
              <ResourceItem resource={resource} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

function ResourceItem({ resource }: { resource: LinkedResource }) {
  const [expanded, setExpanded] = useState(false)
  const isLong = resource.text.length > 220
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ResourceTypeBadge resourceType={resource.resource_type} />
        <span className="text-xs text-slate-500">{formatDate(resource.record_date)}</span>
      </div>
      <p className="mt-2 text-sm font-medium text-slate-900">{resource.title}</p>
      <p
        className={`mt-1 whitespace-pre-line text-sm text-slate-600 ${
          isLong && !expanded ? 'line-clamp-4' : ''
        }`}
      >
        {resource.text}
      </p>
      {isLong ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="mt-1 text-xs font-medium text-teal-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      ) : null}
    </div>
  )
}

function Demographic({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-slate-900">{value}</dd>
    </div>
  )
}

function SummaryField({ label, values }: { label: string; values: string[] }) {
  const cleaned = values.map((value) => value.trim()).filter(Boolean)
  return (
    <div>
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="text-sm text-slate-800">
        {cleaned.length > 0 ? cleaned.join('; ') : 'Not documented'}
      </p>
    </div>
  )
}

function formatMaybe(value: string | null | undefined): string {
  return value && value.trim() ? value : 'Not available'
}

function capitalize(value: string | null): string | null {
  if (!value) {
    return value
  }
  return value.charAt(0).toUpperCase() + value.slice(1)
}

export default PatientDetailDrawer
