import type {
  AdvSuite, DataView, EvalSlipDetail, EvalSummary, FailureAnalysis, Impact, Meta, Posting, ReceiptPosting, ReceiptSample, ReceivingReport, ReceivingSummary, Report, Sample,
  SampleData, ShiftLog, Slip,
} from './types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // keep the status text
    }
    // The page is newer than the running server (Python loads code once, at start).
    if (res.status === 405 || (res.status === 404 && message.startsWith('No API route'))) {
      message = 'The server is running older code than this page. Restart it (python -m slipcheck serve) and reload.'
    }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

export const api = {
  meta: () => fetch('/api/meta').then(json<Meta>),
  samples: () => fetch('/api/samples').then(json<Sample[]>),
  sample: (name: string) => fetch(`/api/samples/${encodeURIComponent(name)}`).then(json<SampleData>),
  /** With a name, the check is recorded in the shift log. */
  validate: (slip: Slip, name: string | null, signal?: AbortSignal) =>
    fetch('/api/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slip, name }),
      signal,
    }).then(json<Report>),
  /** Post to the mock inventory. The server re-checks the slip and refuses duplicates. */
  post: (slip: Slip, name: string, answers: string[]) =>
    fetch('/api/post', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slip, name, answers }),
    }).then(json<Posting>),
  shiftLog: () => fetch('/api/ledger').then(json<ShiftLog>),
  data: () => fetch('/api/data').then(json<DataView>),
  impact: (likely: Record<string, number>) =>
    fetch('/api/impact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ likely }),
    }).then(json<Impact>),
  failures: (split: string) => fetch(`/api/eval/failures?split=${encodeURIComponent(split)}`).then(json<FailureAnalysis>),
  evalSlip: (split: string, slip: string) =>
    fetch(`/api/eval/slip?split=${encodeURIComponent(split)}&slip=${encodeURIComponent(slip)}`).then(json<EvalSlipDetail>),
  /** Check a slip with a named rule set, without recording it in the shift log. */
  validateWith: (slip: Slip, ruleset: string) =>
    fetch('/api/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slip, ruleset }),
    }).then(json<Report>),
  evalSummary: () => fetch('/api/eval/summary').then(json<EvalSummary>),
  /** Runs every adversarial case now, server-side, in throwaway ledgers. */
  adversarial: () => fetch('/api/adversarial').then(json<AdvSuite>),
  clearShiftLog: () => fetch('/api/ledger/reset', { method: 'POST' }).then(json<ShiftLog>),
  events: () => fetch('/api/events').then(json<{ id: number; at: string; kind: string; subject: string; detail: Record<string, unknown> }[]>),
  receiving: {
    samples: () => fetch('/api/receiving/samples').then(json<ReceiptSample[]>),
    sample: (id: string) =>
      fetch(`/api/receiving/samples/${encodeURIComponent(id)}`).then(json<{ reading: Slip; document: string; kind: 'pdf' | 'image' }>),
    /** With a name, the check is recorded for the receiving summary. */
    validate: (receipt: Slip, name: string | null, signal?: AbortSignal) =>
      fetch('/api/receiving/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ receipt, name }),
        signal,
      }).then(json<ReceivingReport>),
    post: (receipt: Slip, name: string, answers: string[]) =>
      fetch('/api/receiving/post', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ receipt, name, answers }),
      }).then(json<ReceiptPosting>),
    summary: () => fetch('/api/receiving/summary').then(json<ReceivingSummary>),
  },
  extract: (file: File, live: boolean) => {
    const form = new FormData()
    form.append('file', file)
    form.append('live', String(live))
    return fetch('/api/extract', { method: 'POST', body: form }).then(json<{ slip: Slip }>)
  },
}
