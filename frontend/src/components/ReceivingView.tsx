import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { issueId, useTrail } from '../evidence'
import { applySet, fieldAt, sameIssue, shown, whereLabel } from '../slip'
import { EvidencePanel } from './EvidencePanel'
import type { FieldSource, Fix, Issue, ReceiptPosting, ReceiptSample, ReceivingReport, ReceivingSummary, Slip } from '../types'

const STATUS_TEXT = { READY: 'Ready to receive', READY_WITH_WARNINGS: 'Ready to receive, with notes', BLOCKED: 'Hold' } as const

/** The field an issue is about, and where on the page it was read from (if that is known). */
function sourceOf(reading: Slip, issue: Issue): FieldSource | null {
  if (!issue.key) return null
  const holder =
    issue.line === null ? reading : (Array.isArray(reading.items) ? (reading.items[issue.line - 1] as Slip | undefined) : undefined)
  if (!holder) return null
  const raw = holder[issue.key]
  return raw && typeof raw === 'object' && 'source' in raw ? ((raw as { source?: FieldSource }).source ?? null) : null
}

export function ReceivingView() {
  const [samples, setSamples] = useState<ReceiptSample[]>([])
  const [selected, setSelected] = useState<ReceiptSample | null>(null)
  const [original, setOriginal] = useState<Slip | null>(null)
  const [reading, setReading] = useState<Slip | null>(null)
  const [report, setReport] = useState<ReceivingReport | null>(null)
  const [summary, setSummary] = useState<ReceivingSummary | null>(null)
  const [active, setActive] = useState<Issue | null>(null)
  const [answers, setAnswers] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [postError, setPostError] = useState<string | null>(null)
  const [opened, setOpened] = useState(0) // each open (or undo) starts a fresh evidence trail
  const [inspect, setInspect] = useState<string | null>(null)
  const trail = useTrail(selected ? `${selected.id}#${opened}` : null, report?.issues, report?.evidence)

  const refresh = useCallback(() => {
    api.receiving.summary().then(setSummary).catch(() => undefined)
  }, [])

  const latest = useRef(0) // a slow response for an earlier pick must not overwrite a later one

  const open = useCallback(async (s: ReceiptSample) => {
    const ticket = ++latest.current
    setSelected(s)
    setActive(null)
    setInspect(null)
    setOpened((n) => n + 1)
    setAnswers([])
    setPostError(null)
    setReport(null)
    try {
      const data = await api.receiving.sample(s.id)
      if (ticket !== latest.current) return
      setOriginal(data.reading)
      setReading(data.reading)
      setError(null)
    } catch (e) {
      if (ticket !== latest.current) return
      setReading(null)
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    refresh()
    api.receiving
      .samples()
      .then((list) => {
        setSamples(list)
        if (list.length) open(list[0])
      })
      .catch((e: Error) => setError(e.message))
  }, [open, refresh])

  useEffect(() => {
    if (!reading || !selected) return
    const ctrl = new AbortController()
    api.receiving
      .validate(reading, selected.id, ctrl.signal)
      .then((r) => {
        setReport(r)
        refresh()
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message))
    return () => ctrl.abort()
  }, [reading, selected, refresh])

  const answer = (issue: Issue, set: Record<string, unknown>, label: string) => {
    if (reading) {
      trail.record(
        issue,
        label,
        Object.keys(set).map((key) => ({
          field: whereLabel(issue.line ? `line ${issue.line} ${key}` : key),
          before: shown(fieldAt(reading, issue.line, key)) || '(blank)',
          after: String(set[key] ?? ''),
        })),
      )
    }
    setReading((prev) => (prev ? applySet(prev, issue.line, set) : prev))
    setAnswers((prev) => [...prev, `${whereLabel(issue.where)}: ${label}`])
    setActive(null)
    setInspect(issueId(issue))
  }

  const pick = (issue: Issue) => {
    setActive(issue)
    setInspect(issueId(issue))
  }

  const onPost = async () => {
    if (!reading || !selected) return
    setPostError(null)
    try {
      const posting = await api.receiving.post(reading, selected.id, answers)
      setReport((r) => (r ? { ...r, posted: posting } : r))
      refresh()
    } catch (e) {
      setPostError((e as Error).message)
    }
  }

  const posted = report?.posted ?? null
  const blocks = report?.issues.filter((i) => i.severity === 'block') ?? []
  const notes = report?.issues.filter((i) => i.severity === 'warn') ?? []
  const done = report?.issues.filter((i) => i.severity === 'info') ?? []
  const counts = summary?.counts

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="max-w-3xl text-graphite-2">
          The other side of the storeroom door: a delivery receipt is checked against its purchase order the moment it
          arrives. PDFs are read from their text layer (exact, with each value&rsquo;s real position on the page); images
          are read by the vision model. Purchase orders and receipts are synthetic; posting writes to a local file only.
        </p>
        {counts && (
          <p className="flex flex-wrap gap-x-5 text-sm text-graphite-2">
            <span><b className="text-stamp">{counts.posted}</b> received</span>
            <span><b className={counts.on_hold ? 'text-redpen' : 'text-graphite'}>{counts.on_hold}</b> on hold</span>
            <span><b className="text-graphite">{counts.problems_caught}</b> problems caught</span>
          </p>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[14rem_minmax(0,1fr)] xl:grid-cols-[14rem_minmax(0,1fr)_27rem]">
        <nav aria-label="Delivery receipts">
          {/* Small screens: one dropdown instead of a long list above the document. */}
          <label className="block lg:hidden">
            <span className="font-cond text-sm font-semibold text-graphite-2">Delivery receipt</span>
            <select
              value={selected?.id ?? ''}
              onChange={(e) => { const s = samples.find((x) => x.id === e.target.value); if (s) open(s) }}
              className="mt-1 block w-full rounded-md border border-rail bg-steel-3 px-3 py-2"
            >
              {samples.map((s) => (
                <option key={s.id} value={s.id}>{s.id}: {s.shows}</option>
              ))}
            </select>
          </label>
          <h2 className="hidden px-2.5 font-cond text-sm font-semibold text-graphite-2 lg:block">Sample delivery receipts</h2>
          <ul className="mt-1 hidden space-y-0.5 lg:block">
            {samples.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => open(s)}
                  aria-current={selected?.id === s.id}
                  className={`w-full cursor-pointer rounded px-2.5 py-1.5 text-left text-sm ${
                    selected?.id === s.id ? 'bg-graphite text-steel-3' : 'hover:bg-steel-3'
                  }`}
                >
                  <span className="font-semibold">{s.id}</span> <span className="opacity-80">{s.kind === 'image' ? '(image) ' : ''}</span>
                  <span className={`block text-xs ${selected?.id === s.id ? 'text-steel-2' : 'text-graphite-2'}`}>{s.shows}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <main className="min-w-0">
          {error && !reading ? (
            <div role="alert" className="rounded-md border-l-4 border-redpen bg-steel-3 p-4">
              <p className="font-semibold">This receipt could not be read.</p>
              <p className="mt-1 text-sm">{error}</p>
            </div>
          ) : selected && reading ? (
            <>
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-sm text-graphite-2">
                <span>
                  <b className="text-graphite">{selected.id}</b>{' '}
                  {selected.kind === 'pdf' ? 'read from the PDF text layer (exact)' : 'read by the vision model (cached reading)'}
                </span>
                {answers.length > 0 && !posted && (
                  <button type="button" className="cursor-pointer underline" onClick={() => original && (setReading(original), setAnswers([]), setInspect(null), setOpened((n) => n + 1))}>
                    Undo answers
                  </button>
                )}
              </div>
              <DocumentWithEvidence id={selected.id} reading={reading} report={report} active={active} onPick={pick} />
              {selected.kind === 'image' && (
                <p className="mt-2 text-xs text-graphite-2">
                  A rendered synthetic image, not a phone photo. Values read by a vision model carry no page coordinates, so
                  none are drawn.
                </p>
              )}
              <EvidencePanel
                title="Evidence for each problem"
                entries={trail.entries}
                selected={inspect}
                onSelect={(id) => {
                  setInspect(id)
                  setActive(report?.issues.find((i) => issueId(i) === id) ?? null)
                }}
                doc={{ kind: selected.kind === 'pdf' ? 'pdf' : 'image', url: `/api/receiving/page/${selected.id}` }}
                postedAs={posted ? `receipt entry #${posted.id}` : null}
              />
            </>
          ) : (
            <p className="text-graphite-2">Pick a receipt on the left.</p>
          )}
        </main>

        <section aria-label="Receiving decision" className="space-y-6 lg:col-start-2 xl:col-start-auto">
          {report && (
            <>
              <div
                role="status"
                className={`rounded-md border-l-4 px-4 py-3 ${
                  posted ? 'border-stamp bg-stamp/10' : report.status === 'BLOCKED' ? 'border-redpen bg-redpen/5' : 'border-stamp bg-steel-3'
                }`}
              >
                <p className="font-cond text-xl font-bold">{posted ? 'Received' : STATUS_TEXT[report.status]}</p>
                <p className="text-sm text-graphite-2">
                  {report.receipt_number ?? 'No receipt number'}, {report.po_number ?? 'no matching PO'}
                  {report.vendor && `, ${report.vendor}`}
                  {report.received_by && `, received by ${report.received_by}`}
                </p>
              </div>

              {blocks.length > 0 && (
                <Group title="Decide before receiving" hint="Each one changes what goes onto the purchase order." issues={blocks}
                  active={active} onPick={pick} onAnswer={answer} />
              )}
              {notes.length > 0 && (
                <Group title="Worth a look" hint="These don't stop the receipt." issues={notes} active={active} onPick={pick} onAnswer={answer} />
              )}

              {report.po_lines.length > 0 && (
                <div>
                  <h2 className="font-cond text-xl font-bold">{report.po_number} after this receipt</h2>
                  <table className="mt-2 w-full text-left text-sm">
                    <thead className="text-graphite-2">
                      <tr className="border-b border-rail/60">
                        <th className="py-1.5 pr-2 font-medium">Part</th>
                        <th className="py-1.5 pr-2 text-right font-medium">Ordered</th>
                        <th className="py-1.5 pr-2 text-right font-medium">Before</th>
                        <th className="py-1.5 pr-2 text-right font-medium">This</th>
                        <th className="py-1.5 text-right font-medium">Open</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.po_lines.map((p) => (
                        <tr key={p.line} className="border-b border-rail/30 align-top">
                          <td className="py-1.5 pr-2">
                            <span className="font-semibold">{p.part_number}</span>
                            <span className={`block text-xs ${p.state === 'over' ? 'text-redpen' : p.state === 'partial' || p.state === 'not delivered' ? 'text-amber' : 'text-graphite-2'}`}>
                              {p.state}
                            </span>
                          </td>
                          <td className="py-1.5 pr-2 text-right">{p.ordered}</td>
                          <td className="py-1.5 pr-2 text-right text-graphite-2">{p.received_before}</td>
                          <td className="py-1.5 pr-2 text-right font-semibold">{p.this_receipt}</td>
                          <td className="py-1.5 text-right">
                            {p.open_after} {p.unit}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div>
                <button
                  type="button"
                  disabled={report.status === 'BLOCKED' || !!posted}
                  onClick={onPost}
                  className="w-full rounded-md bg-graphite px-4 py-2.5 font-cond text-lg font-semibold text-steel-3 enabled:cursor-pointer enabled:hover:bg-graphite-2 disabled:cursor-not-allowed disabled:bg-rail/50 disabled:text-graphite-2"
                >
                  {posted ? 'Received' : report.status === 'BLOCKED' ? `Decide ${blocks.length} to receive` : 'Receive against the PO'}
                </button>
                {posted && <PostedNote posting={posted} />}
                {postError && (
                  <p role="alert" className="mt-2 text-sm font-medium text-redpen">
                    Not received: {postError}
                  </p>
                )}
              </div>

              {(done.length > 0 || answers.length > 0) && (
                <div>
                  <h2 className="font-cond text-lg font-bold">Done for you</h2>
                  <ul className="mt-1.5 space-y-1 text-sm text-graphite-2">
                    {done.map((i) => (
                      <li key={i.code + i.where}>{i.message}</li>
                    ))}
                    {answers.map((a, n) => (
                      <li key={n} className="text-stamp">
                        Answered: {a}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}

function DocumentWithEvidence(props: {
  id: string
  reading: Slip
  report: ReceivingReport | null
  active: Issue | null
  onPick: (i: Issue) => void
}) {
  const marks = (props.report?.issues ?? [])
    .filter((i) => i.severity !== 'info')
    .map((i) => ({ issue: i, src: sourceOf(props.reading, i) }))
    .filter((m): m is { issue: Issue; src: FieldSource } => !!m.src?.bbox && !!m.src.page_size)
  return (
    <div className="relative overflow-hidden rounded border border-rail bg-white shadow-sm">
      <img src={`/api/receiving/page/${props.id}`} alt={`Delivery receipt ${props.id}`} className="block w-full" />
      {marks.map(({ issue, src }) => {
        const [x0, y0, x1, y1] = src.bbox!
        const [w, h] = src.page_size!
        const on = sameIssue(props.active, issue)
        return (
          <button
            key={issue.code + issue.where}
            type="button"
            title={`${issue.code}: ${issue.message}`}
            aria-label={`Show where ${whereLabel(issue.where)} was read`}
            onClick={() => props.onPick(issue)}
            className={`absolute cursor-pointer rounded-sm border-2 ${
              issue.severity === 'block' ? 'border-redpen' : 'border-amber'
            } ${on ? 'bg-redpen/20 ring-4 ring-redpen/30' : 'bg-transparent hover:bg-redpen/10'}`}
            style={{ left: `${(x0 / w) * 100 - 0.6}%`, top: `${(y0 / h) * 100 - 0.4}%`,
                     width: `${((x1 - x0) / w) * 100 + 1.2}%`, height: `${((y1 - y0) / h) * 100 + 0.8}%` }}
          />
        )
      })}
    </div>
  )
}

function Group(props: {
  title: string
  hint: string
  issues: Issue[]
  active: Issue | null
  onPick: (i: Issue) => void
  onAnswer: (i: Issue, set: Record<string, unknown>, label: string) => void
}) {
  return (
    <div>
      <h2 className="font-cond text-xl font-bold">{props.title}</h2>
      <p className="text-sm text-graphite-2">{props.hint}</p>
      <ul className="mt-2 space-y-2">
        {props.issues.map((i) => (
          <Question key={i.code + i.where} issue={i} active={props.active} onPick={props.onPick} onAnswer={props.onAnswer} />
        ))}
      </ul>
    </div>
  )
}

function Question({ issue, active, onPick, onAnswer }: {
  issue: Issue
  active: Issue | null
  onPick: (i: Issue) => void
  onAnswer: (i: Issue, set: Record<string, unknown>, label: string) => void
}) {
  const [text, setText] = useState('')
  const typed = !!issue.key && issue.severity === 'block' && !issue.fixes.length
  return (
    <li className={`rounded-md border-l-4 bg-steel-3 px-3 py-2.5 ${issue.severity === 'block' ? 'border-redpen' : 'border-amber'} ${
      sameIssue(active, issue) ? 'ring-2 ring-ballpoint/50' : ''}`}>
      <button type="button" onClick={() => onPick(issue)} className="w-full cursor-pointer text-left">
        <span className="block text-xs font-medium text-graphite-2">{whereLabel(issue.where)}</span>
        <span className="mt-0.5 block text-[0.95rem] leading-snug">{issue.message}</span>
      </button>
      {issue.fixes.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {issue.fixes.map((f: Fix) => (
            <button key={f.label} type="button" onClick={() => onAnswer(issue, f.set, f.label)}
              className="cursor-pointer rounded border border-graphite/25 bg-white px-2 py-1 text-sm hover:border-stamp hover:text-stamp">
              {f.label}
            </button>
          ))}
        </div>
      )}
      {typed && (
        <form className="mt-2 flex gap-1.5" onSubmit={(e) => { e.preventDefault(); if (text.trim()) onAnswer(issue, { [issue.key!]: text.trim() }, text.trim()) }}>
          <label className="sr-only" htmlFor={`rcv-${issue.code}-${issue.where}`}>Value for {issue.where}</label>
          <input id={`rcv-${issue.code}-${issue.where}`} value={text} onChange={(e) => setText(e.target.value)}
            inputMode={issue.code === 'BLIND_COUNT' || issue.code === 'BAD_COUNT' ? 'numeric' : undefined}
            placeholder={issue.code === 'MISSING_RECEIVED_BY' ? 'Name of the person receiving'
              : issue.code === 'BLIND_COUNT' || issue.code === 'BAD_COUNT' ? 'How many you counted' : 'Correct value'}
            className="min-w-0 flex-1 rounded border border-graphite/25 bg-white px-2 py-1 text-sm" />
          <button type="submit" className="cursor-pointer rounded bg-graphite px-3 py-1 text-sm font-medium text-steel-3 hover:bg-graphite-2">Confirm</button>
        </form>
      )}
    </li>
  )
}

function PostedNote({ posting }: { posting: ReceiptPosting }) {
  const at = new Date(posting.posted_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return (
    <p className="mt-2 text-sm text-graphite-2">
      Received as entry {posting.id} at {at}: {posting.lines.length} {posting.lines.length === 1 ? 'line' : 'lines'} added to{' '}
      {posting.po_number}
      {posting.held.length > 0 && `; ${posting.held.join(', ')}`}. Mocked: saved on this computer only.
    </p>
  )
}

