// Types mirroring the FastAPI backend responses.

export type ResourceType = 'DocumentReference' | 'DiagnosticReport'

export type Confidence = 'low' | 'medium' | 'high'

export interface SearchResultItem {
  patient_id: string
  patient_name: string
  mrn: string
  resource_id: string
  resource_type: string
  record_date: string | null
  title: string
  relevance_score: number
  resource_text_snippet: string
  clinical_summary_snippet: string | null
}

export interface SearchResponse {
  query: string
  result_count: number
  elapsed_ms: number
  results: SearchResultItem[]
}

export interface SearchFilters {
  resourceType: ResourceType | ''
  dateFrom: string
  dateTo: string
}

export interface ClinicalSummary {
  patient_id: string
  chief_concern: string
  key_diagnoses: string[]
  recent_media_records: string[]
  flagged_anomalies: string[]
  confidence: Confidence
  disclaimer: string
  source_resource_ids: string[]
  word_count: number
}

export interface LinkedResource {
  resource_id: string
  resource_type: string
  record_date: string | null
  title: string
  text: string
}

export interface PatientDetail {
  patient_id: string
  patient_name: string
  mrn: string
  date_of_birth: string | null
  gender: string | null
  bundle_valid: boolean
  summary: ClinicalSummary | null
  summary_confidence: string | null
  summary_disclaimer: string | null
  resources: LinkedResource[]
}
