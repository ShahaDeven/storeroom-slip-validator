// Mirrors slipcheck/validate.py (Report.to_dict) and slipcheck/api.py.

export type Severity = 'block' | 'warn' | 'info'
export type Status = 'READY' | 'READY_WITH_WARNINGS' | 'BLOCKED'
export type Slip = Record<string, unknown>

export interface Fix {
  label: string
  set: Record<string, unknown>
}

export interface Issue {
  severity: Severity
  code: string
  where: string
  message: string
  ask: 'crew' | 'desk'
  suggestions: string[]
  fixes: Fix[]
  line: number | null
  key: string | null
}

export interface Line {
  line: number
  part_number: string | null
  name: string | null
  aisle: string | null
  qty: number | null
  unit: string | null
}

export interface Report {
  status: Status
  wo_number: string | null
  crew: string | null
  taken_by: string | null
  location: string | null
  slip_date: string | null
  lines: Line[]
  issues: Issue[]
  posted?: Posting | null
}

export interface Sample {
  name: string
  kind: 'slip' | 'photo'
  note: string | null
}

export interface Meta {
  live_available: boolean
  model: string
  parts: number
  work_orders: number
}

export interface SampleData {
  slip: Slip | null
  photo?: string | null
  raw?: string
  error?: string
}

export interface Posting {
  id: number
  name: string
  posted_at: string
  wo_number: string | null
  crew: string | null
  taken_by: string | null
  location: string | null
  slip_date: string | null
  lines: { part_number: string | null; name: string | null; aisle: string | null; qty: number | null; unit: string | null }[]
  answers: string[]
}

export interface Pending {
  name: string
  status: Status
  open_codes: string[]
  needs_review: boolean
  wo_number: string | null
  taken_by: string | null
  crew: string | null
  last_seen: string
}

export interface ShiftLog {
  counts: {
    checked: number
    posted: number
    on_hold: number
    ready_unposted: number
    needs_review: number
    caught: number
    resolved_at_counter: number
  }
  postings: Posting[]
  pending: Pending[]
  caught: { code: string; severity: Severity; count: number }[]
  stock: { part_number: string; name: string; aisle: string; unit: string; start: number; posted: number; on_hand: number; low: boolean }[]
}
