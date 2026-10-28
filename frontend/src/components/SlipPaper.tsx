import type { ReactNode } from 'react'
import { fieldAt, issuesAt, items, MARGIN_NOTE, pinKey, sameIssue, shown } from '../slip'
import type { Issue, Report, Slip } from '../types'

interface Props {
  slip: Slip
  report: Report | null
  corrections: Record<string, string>
  active: Issue | null
  onPick: (issue: Issue) => void
  posted: boolean
}

export function SlipPaper({ slip, report, corrections, active, onPick, posted }: Props) {
  const issues = report?.issues ?? []
  const rows = items(slip)

  const value = (line: number | null, key: string, className = '') => (
    <Written
      line={line}
      field={key}
      slip={slip}
      issues={issuesAt(issues, line, key)}
      was={corrections[pinKey(line, key)]}
      active={active}
      onPick={onPick}
      className={className}
    />
  )

  return (
    <div className="paper relative px-5 pt-7 pb-6 sm:px-8">
      {report && <Stamp report={report} posted={posted} />}

      <div className="flex items-baseline justify-between gap-4 pr-28 text-form-ink">
        <h2 className="font-cond text-lg font-bold tracking-wide">Storeroom parts checkout slip</h2>
      </div>
      <p className="mb-5 font-cond text-xs text-form-ink/80">Synthetic form for the prototype</p>

      <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
        <Blank label="W/O no.">{value(null, 'wo_number')}</Blank>
        <Blank label="Date">{value(null, 'date')}</Blank>
        <Blank label="Taken by">{value(null, 'taken_by')}</Blank>
        <Blank label="Location">{value(null, 'location')}</Blank>
      </div>

      <div className="mt-6">
        <table className="w-full table-fixed border-collapse text-left [overflow-wrap:anywhere]">
          <thead>
            <tr className="font-cond text-xs font-semibold text-form-ink">
              <th className="w-[26%] border border-form-ink/70 px-1.5 py-1 sm:px-2">Part no.</th>
              <th className="border border-form-ink/70 px-1.5 py-1 sm:px-2">Description</th>
              <th className="w-[17%] border border-form-ink/70 px-1.5 py-1 sm:w-[11%] sm:px-2">Qty</th>
              <th className="w-[19%] border border-form-ink/70 px-1.5 py-1 sm:w-[12%] sm:px-2">Unit</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const n = i + 1
              const lineIssues = issues.filter((x) => x.line === n && x.key === null)
              return (
                <tr key={n} className="align-top">
                  {typeof row === 'object' && row !== null ? (
                    <>
                      <td className="border border-form-ink/70 px-2 py-1.5">{value(n, 'part_number')}</td>
                      <td className="border border-form-ink/70 px-2 py-1.5">{value(n, 'part_name')}</td>
                      <td className="border border-form-ink/70 px-2 py-1.5">{value(n, 'qty')}</td>
                      <td className="border border-form-ink/70 px-2 py-1.5">{value(n, 'unit')}</td>
                    </>
                  ) : (
                    <td colSpan={4} className="border border-form-ink/70 px-2 py-1.5">
                      <span className="font-hand text-lg text-ballpoint wavy-block">{String(row)}</span>
                      <Notes issues={lineIssues} active={active} onPick={onPick} />
                    </td>
                  )}
                </tr>
              )
            })}
            {rows.length < 3 &&
              Array.from({ length: 3 - rows.length }, (_, i) => (
                <tr key={`empty-${i}`} aria-hidden>
                  {[0, 1, 2, 3].map((c) => (
                    <td key={c} className="h-10 border border-form-ink/70" />
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <div className="mt-6 grid gap-x-8 gap-y-4 sm:grid-cols-2">
        <Blank label="Signature">
          <Signature slip={slip} issues={issuesAt(issues, null, 'signature')} was={corrections[pinKey(null, 'signature')]} active={active} onPick={onPick} />
        </Blank>
        <Blank label="Issued by">
          <span className="font-hand text-lg text-stamp">{posted ? 'storeroom desk' : ''}</span>
        </Blank>
      </div>
    </div>
  )
}

function Blank({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-end gap-3">
      <span className="shrink-0 pb-1 font-cond text-sm font-semibold text-form-ink">{label}</span>
      <div className="blank min-h-9 min-w-0 flex-1 pb-0.5">{children}</div>
    </div>
  )
}

interface WrittenProps {
  line: number | null
  field: string
  slip: Slip
  issues: Issue[]
  was?: string
  active: Issue | null
  onPick: (issue: Issue) => void
  className?: string
}

function Written({ line, field, slip, issues, was, active, onPick, className = '' }: WrittenProps) {
  const f = fieldAt(slip, line, field)
  const text = shown(f)
  const worst = issues.find((i) => i.severity === 'block') ?? issues.find((i) => i.severity === 'warn')
  const mark = worst?.severity === 'block' ? 'wavy-block' : worst?.severity === 'warn' ? 'wavy-warn' : ''
  const unsure = f.confidence < 1
  const title = unsure ? `Read from photo with ${Math.round(f.confidence * 100)}% confidence` : undefined

  return (
    <span className={`inline-flex flex-wrap items-baseline gap-x-2 gap-y-1.5 ${className}`}>
      {was !== undefined && (
        <span className="font-hand text-base text-ballpoint/60 line-through decoration-redpen decoration-2">
          {was || 'blank'}
        </span>
      )}
      <span
        title={title}
        className={`font-hand text-lg leading-tight ${was !== undefined ? 'text-stamp' : 'text-ballpoint'} ${mark} ${
          f.value === null && f.raw ? 'opacity-60' : ''
        }`}
      >
        {text || ' '}
      </span>
      <Notes issues={issues} active={active} onPick={onPick} />
    </span>
  )
}

function Notes({ issues, active, onPick }: { issues: Issue[]; active: Issue | null; onPick: (i: Issue) => void }) {
  const shownIssues = issues.filter((i) => i.severity !== 'info')
  if (!shownIssues.length) return null
  return (
    <>
      {shownIssues.map((i) => (
        <button
          key={i.code + i.where}
          type="button"
          onClick={() => onPick(i)}
          className={`-rotate-2 cursor-pointer rounded-sm px-1 font-hand text-sm leading-none ${
            i.severity === 'block' ? 'text-redpen' : 'text-amber'
          } ${sameIssue(active, i) ? 'bg-white/60 ring-1 ring-current' : 'hover:bg-white/40'}`}
        >
          {MARGIN_NOTE[i.code] ?? i.code.toLowerCase()}
        </button>
      ))}
    </>
  )
}

function Signature(props: { slip: Slip; issues: Issue[]; was?: string; active: Issue | null; onPick: (i: Issue) => void }) {
  const f = fieldAt(props.slip, null, 'signature')
  const signed = f.value === true || (typeof f.value === 'string' && f.value.trim() !== '')
  return (
    <span className="inline-flex items-end gap-2">
      {signed && (
        <svg viewBox="0 0 120 32" className={`h-8 w-28 ${props.was !== undefined ? 'text-stamp' : 'text-ballpoint'}`} aria-label="Signed">
          <path
            d="M4 24c8-14 14-18 16-10s-4 12 2 6 8-16 14-10-2 14 6 8 10-12 16-6 4 8 12 2 10-8 16-4 8 6 26-2"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>
      )}
      <Notes issues={props.issues} active={props.active} onPick={props.onPick} />
    </span>
  )
}

function Stamp({ report, posted }: { report: Report; posted: boolean }) {
  const blocks = report.issues.filter((i) => i.severity === 'block').length
  const warns = report.issues.filter((i) => i.severity === 'warn').length
  const s = posted
    ? { text: 'Posted', sub: 'to inventory', cls: 'text-stamp' }
    : report.status === 'BLOCKED'
      ? { text: 'Hold', sub: `${blocks} to resolve`, cls: 'text-redpen' }
      : { text: 'Ready to post', sub: warns ? `${warns} ${warns === 1 ? 'note' : 'notes'}` : 'no issues', cls: 'text-stamp' }
  return (
    <div
      key={s.text}
      role="status"
      className={`stamp pointer-events-none absolute top-4 right-4 px-3 py-1 text-center font-cond uppercase sm:top-6 sm:right-8 ${s.cls}`}
    >
      <div className="text-2xl leading-none font-bold tracking-wider sm:text-3xl">{s.text}</div>
      <div className="text-[0.7rem] font-semibold tracking-wide">{s.sub}</div>
    </div>
  )
}
