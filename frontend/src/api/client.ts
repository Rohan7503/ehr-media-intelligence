// Small typed Fetch wrapper for the EHR Media Intelligence API.
//
// The base URL is configurable via VITE_API_BASE_URL and defaults to the local
// FastAPI dev server. Errors from FastAPI (both `{detail: string}` and the
// validation `{detail: [{msg}]}` shape) are turned into readable messages, and
// non-JSON failures are handled gracefully. Requests accept an AbortSignal so
// callers can cancel in-flight work.

import type { PatientDetail, SearchFilters, SearchResponse } from './types'

const BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

/** A readable error carrying the HTTP status, thrown by the API client. */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface FastApiValidationItem {
  msg?: string
}

function readErrorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') {
      return detail
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item: FastApiValidationItem) => item?.msg)
        .filter((msg): msg is string => typeof msg === 'string')
      if (messages.length > 0) {
        return messages.join('; ')
      }
    }
  }
  return `Request failed (${status})`
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, init)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new ApiError(
      'Could not reach the backend. Is the API running?',
      0,
    )
  }

  const body = await parseJson(response)
  if (!response.ok) {
    throw new ApiError(readErrorMessage(body, response.status), response.status)
  }
  return body as T
}

function buildSearchQuery(filters: SearchFilters): string {
  const params = new URLSearchParams()
  if (filters.resourceType) {
    params.set('resource_type', filters.resourceType)
  }
  if (filters.dateFrom) {
    params.set('date_from', filters.dateFrom)
  }
  if (filters.dateTo) {
    params.set('date_to', filters.dateTo)
  }
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

export async function search(
  query: string,
  filters: SearchFilters,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  return request<SearchResponse>(`/search${buildSearchQuery(filters)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
    signal,
  })
}

export async function getPatient(
  patientId: string,
  signal?: AbortSignal,
): Promise<PatientDetail> {
  return request<PatientDetail>(
    `/patients/${encodeURIComponent(patientId)}`,
    { method: 'GET', signal },
  )
}
