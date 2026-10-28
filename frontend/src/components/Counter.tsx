import { useEffect, useRef, useState } from 'react'
import { sameIssue, whereLabel } from '../slip'
import type { Fix, Issue, Posting, Report } from '../types'

interface Props {
  report: Report
  active: Issue | null
  onPick: (issue: Issue) => void
  onFix: (issue: Issue, fix: Fix) => void
  onEnter: (issue: Issue, value: string) => void
  log: string[]
  posting: Posting | null
  postError: string | null
  onPost: () => void
  onShowLog: () => void
}

/** The clerk's side of the counter: who to call, what to ask, what posts. */
export function Counter({ report, active, onPick, onFix, onEnter, log, posting, postError, onPost, onShowLog }: Props) {
  const posted = !!posting
  const blocks = report.issues.filter((i) => i.severity === 'block')
  const crew = blocks.filter((i) => i.ask === 'crew')
  const desk = blocks.filter((i) => i.ask === 'desk')
  const warns = report.issues.filter((i) => i.severity === 'warn')
  const auto = report.issues.filter((i) => i.severity === 'info')
  const who = report.taken_by || 'the crew'

  return (
    <div className="space-y-7">
      {crew.length > 0 && (
        <section>
          <h2 className="font-cond text-xl font-bold">
            Call {who}
            {report.crew && <span className="font-semibold text-graphite-2"> ({report.crew})</span>}
          </h2>
          <p className="mt-1 text-sm text-graphite-2">
            {crew.length === 1 ? 'One question' : `${crew.length} questions`} before these parts can post.
            They took the parts minutes ago, so they still know the answers.
          </p>
          <ol className="mt-3 space-y-2">
            {crew.map((i) => (
              <Question key={i.code + i.where} issue={i} active={active} onPick={onPick} onFix={onFix} onEnter={onEnter} />
            ))}
          </ol>
        </section>
      )}

      {desk.length > 0 && (
        <section>
          <h2 className="font-cond text-xl font-bold">Check at the desk</h2>
          <p className="mt-1 text-sm text-graphite-2">Answerable from the paper slip or the shelf.</p>
          <ol className="mt-3 space-y-2">
            {desk.map((i) => (
              <Question key={i.code + i.where} issue={i} active={active} onPick={onPick} onFix={onFix} onEnter={onEnter} />
            ))}
          </ol>
        </section>
      )}

      <section>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="font-cond text-xl font-bold">Entry to post</h2>
          <span className="text-sm text-graphite-2">
            W/O {report.wo_number ?? 'unknown'}, {report.location ?? 'no location'}
          </span>
        </div>
        <table className="mt-2 w-full text-left text-sm">
          <thead className="text-graphite-2">
            <tr className="border-b border-rail/60">
              <th className="py-1.5 pr-2 font-medium">Part</th>
              <th className="py-1.5 pr-2 font-medium">Aisle</th>
              <th className="py-1.5 text-right font-medium">Qty</th>
            </tr>
          </thead>
          <tbody>
            {report.lines.map((l) => (
              <tr key={l.line} className="border-b border-rail/30 align-top">
                <td className="py-2 pr-2">
                  {l.part_number ? (
                    <>
                      <div className="font-semibold">{l.part_number}</div>
                      <div className="text-graphite-2">{l.name}</div>
                    </>
                  ) : (
                    <span className="font-semibold text-redpen">Line {l.line}: part not resolved</span>
                  )}
                </td>
                <td className="py-2 pr-2">{l.aisle ?? ''}</td>
                <td className="py-2 text-right whitespace-nowrap">
                  {l.qty !== null ? `${l.qty} ${l.unit ?? ''}` : <span className="font-semibold text-redpen">unresolved</span>}
                </td>
              </tr>
            ))}
            {!report.lines.length && (
              <tr>
                <td colSpan={3} className="py-2 text-graphite-2">No lines on this slip.</td>
              </tr>
            )}
          </tbody>
        </table>
        <button
          type="button"
          disabled={report.status === 'BLOCKED' || posted}
          onClick={onPost}
          className="mt-4 w-full rounded-md bg-graphite px-4 py-2.5 font-cond text-lg font-semibold text-steel-3 enabled:hover:bg-graphite-2 disabled:cursor-not-allowed disabled:bg-rail/50 disabled:text-graphite-2"
        >
          {posted ? 'Posted' : report.status === 'BLOCKED' ? `Resolve ${blocks.length} to post` : 'Post to inventory'}
        </button>
        {posting && (
          <p className="mt-2 text-sm text-graphite-2">
            Posted as entry {posting.id} at{' '}
            {new Date(posting.posted_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}, and stock was
            lowered. Mocked inventory: saved on this computer only.{' '}
            <button type="button" onClick={onShowLog} className="cursor-pointer underline">
              See the shift log
            </button>
          </p>
        )}
        {postError && (
          <p role="alert" className="mt-2 text-sm font-medium text-redpen">
            Not posted: {postError}
          </p>
        )}
      </section>

      {warns.length > 0 && (
        <section>
          <h2 className="font-cond text-lg font-bold">Worth a look</h2>
          <p className="mt-0.5 text-sm text-graphite-2">These don't stop posting.</p>
          <ul className="mt-2 space-y-2">
            {warns.map((i) => (
              <Question key={i.code + i.where} issue={i} active={active} onPick={onPick} onFix={onFix} onEnter={onEnter} />
            ))}
          </ul>
        </section>
      )}

      {(auto.length > 0 || log.length > 0) && (
        <section>
          <h2 className="font-cond text-lg font-bold">Done for you</h2>
          <ul className="mt-2 space-y-1.5 text-sm text-graphite-2">
            {auto.map((i) => (
              <li key={i.code + i.where}>{i.message}</li>
            ))}
            {log.map((entry, n) => (
              <li key={n} className="text-stamp">
                Answered: {entry}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

interface QuestionProps {
  issue: Issue
  active: Issue | null
  onPick: (issue: Issue) => void
  onFix: (issue: Issue, fix: Fix) => void
  onEnter: (issue: Issue, value: string) => void
}

function Question({ issue, active, onPick, onFix, onEnter }: QuestionProps) {
  const ref = useRef<HTMLLIElement>(null)
  const [text, setText] = useState('')
  const isActive = sameIssue(active, issue)
  // Free entry where there is no list to pick from, or when a read was not trusted.
  const canType = !!issue.key && (issue.code === 'HUMAN_REVIEW' || (issue.severity === 'block' && !issue.fixes.length))

  useEffect(() => {
    if (isActive) ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [isActive])

  const tone = issue.severity === 'block' ? 'border-redpen' : 'border-amber'

  return (
    <li
      ref={ref}
      className={`rounded-md border-l-4 bg-steel-3 px-3 py-2.5 ${tone} ${isActive ? 'ring-2 ring-ballpoint/50' : ''}`}
    >
      <button type="button" onClick={() => onPick(issue)} className="w-full cursor-pointer text-left">
        <span className="block text-xs font-medium text-graphite-2">{whereLabel(issue.where)}</span>
        <span className="mt-0.5 block text-[0.95rem] leading-snug">{issue.message}</span>
      </button>

      {issue.fixes.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {issue.fixes.map((f) => (
            <button
              key={f.label}
              type="button"
              onClick={() => onFix(issue, f)}
              className="cursor-pointer rounded border border-graphite/25 bg-white px-2 py-1 text-sm hover:border-stamp hover:text-stamp"
            >
              {f.label}
            </button>
          ))}
        </div>
      )}

      {canType && (
        <form
          className="mt-2 flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            if (text.trim()) onEnter(issue, text.trim())
          }}
        >
          <label className="sr-only" htmlFor={`fix-${issue.code}-${issue.where}`}>
            Correct value for {issue.where}
          </label>
          <input
            id={`fix-${issue.code}-${issue.where}`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={issue.code === 'HUMAN_REVIEW' ? 'What the paper slip says' : 'Correct value'}
            className="min-w-0 flex-1 rounded border border-graphite/25 bg-white px-2 py-1 text-sm"
          />
          <button
            type="submit"
            className="cursor-pointer rounded bg-graphite px-3 py-1 text-sm font-medium text-steel-3 hover:bg-graphite-2"
          >
            Confirm
          </button>
        </form>
      )}
    </li>
  )
}
