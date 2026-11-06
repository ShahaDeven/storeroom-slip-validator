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
  /** evidence[i] explains issues[i] */
  evidence?: Evidence[]
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

export interface Stamp {
  posting_id: number
  posted_at: string
}

export interface PartRow {
  part_number: string
  name: string
  unit: string
  unit_size: number
  aisle: string
  start: number
  on_hand: number
  posted: number
  max_per_pull: number
  low: boolean
  last: (Stamp & { qty: number }) | null
}

export interface WorkOrderRow {
  wo_number: string
  status: 'OPEN' | 'CLOSED'
  crew: string
  members: string[]
  location: string
  opened: string
  closed: string | null
  postings: number
  lines: number
  last: Stamp | null
}

export interface StockChange extends Stamp {
  part_number: string
  name: string | null
  unit: string | null
  qty: number
  before: number
  after: number
  wo_number: string | null
  taken_by: string | null
}

export interface DataView {
  parts: PartRow[]
  work_orders: WorkOrderRow[]
  changes: StockChange[]
  latest_posting_id: number | null
}

export interface Range {
  low: number
  likely: number
  high: number
  source: 'observed' | 'assumed' | 'unknown'
  basis: string
}

export interface ImpactScenario {
  detection_weighted: number
  mismatches_per_week: { manual: number; checked: number }
  hours_per_week: { manual: number; checked: number; saved: number }
  hours_per_year_saved: number
  dollars_per_year_saved: number
  flags_per_week: number
  audit_variances_per_year: { manual: number; checked: number }
  corrections_logged_per_year: number
  break_even_slip_share: number | null
}

export interface Impact {
  detection: Record<string, { label: string; n: number; flagged: number; auto_ok: number; auto_wrong: number; missed: number; caught: number }>
  false_alarm_rate: number
  scenarios: { pessimistic: ImpactScenario; likely: ImpactScenario; optimistic: ImpactScenario }
  likely_inputs: Record<string, number>
  assumptions: Record<string, unknown> & {
    excluded: Record<string, { source: string; basis: string }>
    error_mix: { source: string; basis: string; shares: Record<string, number> }
  }
  settings: { n_per_type: number; seed: number }
}

// ---------------------------------------------------------------- receiving

export interface FieldSource {
  document: string
  page?: number
  page_size?: [number, number]
  bbox?: [number, number, number, number] | null
  method: string
  field: string
  line: number | null
}

export interface ReceiptLine {
  line: number
  part_number: string | null
  description: string | null
  po_line: number | null
  written: string | null
  qty: number | null
  unit: string | null
  counts: boolean
  disposition: string | null
}

export interface POLineState {
  line: number
  part_number: string
  description: string
  unit: string
  ordered: number
  received_before: number
  this_receipt: number
  open_after: number
  state: string
}

export interface ReceiptPosting {
  id: number
  name: string
  receipt_number: string
  po_number: string
  posted_at: string
  received_by: string | null
  lines: { part_number: string; qty: number; unit: string }[]
  held: string[]
  answers: string[]
}

export interface ReceivingReport {
  status: Status
  receipt_number: string | null
  po_number: string | null
  vendor: string | null
  received_on: string | null
  received_by: string | null
  lines: ReceiptLine[]
  po_lines: POLineState[]
  issues: Issue[]
  posted?: ReceiptPosting | null
  evidence?: Evidence[]
}

export interface ReceiptSample {
  id: string
  file: string
  kind: 'pdf' | 'image'
  receipt_number: string
  po_number: string
  shows: string
}

export interface ReceivingSummary {
  counts: { checked: number; posted: number; on_hold: number; problems_caught: number }
  receipts: ReceiptPosting[]
  pending: { name: string; status: Status; open_codes: string[]; po_number: string | null; receipt_number: string | null }[]
  caught: { code: string; count: number }[]
  pos: {
    po_number: string
    vendor: string
    status: 'OPEN' | 'CLOSED'
    ordered_on: string
    lines: { line: number; part_number: string; description: string; unit: string; ordered: number; received: number; open: number }[]
  }[]
}

// ------------------------------------------------------------ adversarial suite

export type AdvOutcome = 'posted' | 'posted_with_warnings' | 'blocked' | 'needs_review' | 'refused'
export type AdvVerdict = 'as_expected' | 'known_gap' | 'regression'

export interface AdvCase {
  id: string
  area: 'receiving' | 'slips'
  title: string
  attempt: string
  expect: AdvOutcome
  expect_codes: string[]
  why: string
  known_gap: string | null
  history: string | null
  setup: { say: string; outcome: AdvOutcome }[]
  attempt_step: string
  actual: { outcome: AdvOutcome; status: string | null; codes: string[]; message: string | null }
  verdict: AdvVerdict
  got_in: boolean
}

export interface AdvSuite {
  ran_at: string
  today: string
  ms: number
  total: number
  counts: Record<AdvVerdict, number>
  got_in: number
  cases: AdvCase[]
}

// ------------------------------------------------------------ evaluation (measured, from saved results)

export interface Prop {
  k: number
  n: number
  rate: number | null
  ci95: [number, number]
}

export interface EvalSplit {
  slips: number
  review_rate: Prop
  unnecessary_review: Prop
  critical_fields_correct: Prop
  reaches_posting: {
    slips_with_wrong_critical_value: Prop
    slips_with_any_wrong_value: Prop
    warned_only: number
  } | null
  commit: string | null
}

export interface EvalSummary {
  dev: EvalSplit | null
  heldout_locked: EvalSplit | null
  heldout_corrected: EvalSplit | null
}

// ------------------------------------------------------------ failure analysis

export type Fate = 'stopped' | 'warned_only' | 'nothing_raised'

export interface FailureAnalysis {
  split: string
  title: string
  source: string
  commit: string | null
  strict_known: boolean
  splits: { key: string; title: string }[]
  tiles: {
    slips: number
    posting_wrong_critical: Prop
    posting_wrong_any: Prop
    slips_reviewed: Prop
    confident_wrong: { k: number; n: number }
  }
  findings: string[]
  by_field: {
    field: string
    label: string
    fields: number
    wrong: number
    stopped: number
    warned_only: number
    nothing_raised: number
    posted: number
    critical: 'always' | 'when no part number' | 'no'
  }[]
  false_positives: { field: string; label: string; reviews: number; rule_flags: number }[]
  unnecessary_reviews: Prop
  misses: {
    slip: string
    style: string
    condition: string
    field: string
    line: number | null
    paper: string
    read: string
    confidence: number | null
    critical: boolean
    fate: Fate
    kind: string
    posted: boolean
  }[]
  miss_kinds: { kind: string; count: number }[]
  confidence: {
    bins: { from: number; to: number; correct: number; wrong: number }[]
    below: number
    threshold: number
    no_confidence: number
  }
  reviews: {
    per_slip: { slip: string; style: string; reviews: number; needless: number; posted_wrong: number }[]
    histogram: { reviews: number; slips: number }[]
  }
  by_style: FailureGroup[]
  by_condition: FailureGroup[]
}

export interface FailureGroup {
  key: string
  label: string
  slips: number
  fields_correct: Prop
  slips_reviewed: number
  slips_posting_wrong: number
}

// ------------------------------------------------------------ evidence for each discrepancy

export interface Evidence {
  rule: { code: string; text: string; checks_against: string; outcome: string }
  extracted: {
    field: string
    line: number | null
    value: unknown
    raw: string | null
    confidence: number
    source: (FieldSource & { model?: string; extracted_at?: string; review_status?: string }) | null
  } | null
  reference: { title: string; rows: [string, string][]; candidates: string[] } | null
}
