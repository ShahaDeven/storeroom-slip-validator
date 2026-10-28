import type { Meta, Posting, Report, Sample, SampleData, ShiftLog, Slip } from './types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // keep the status text
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
  clearShiftLog: () => fetch('/api/ledger/reset', { method: 'POST' }).then(json<ShiftLog>),
  extract: (file: File, live: boolean) => {
    const form = new FormData()
    form.append('file', file)
    form.append('live', String(live))
    return fetch('/api/extract', { method: 'POST', body: form }).then(json<{ slip: Slip }>)
  },
}
