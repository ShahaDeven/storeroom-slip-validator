import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { AdvCase, AdvOutcome, AdvSuite, AdvVerdict } from '../types'

type Filter = 'all' | 'got_in' | 'receiving' | 'slips'

const OUTCOME: Record<AdvOutcome, string> = {
  posted: 'Posted',
  posted_with_warnings: 'Posted, with warnings',
  blocked: 'Stopped until a person answers',
  needs_review: 'Sent to a person to check the paper',
  refused: 'Refused at posting',
}
const STOPS = new Set<AdvOutcome>(['blocked', 'needs_review', 'refused'])

const VERDICT: Record<AdvVerdict, { label: string; cls: string }> = {
  as_expected: { label: 'As expected', cls: 'text-stamp' },
  known_gap: { label: 'Known gap', cls: 'text-redpen' },
  regression: { label: 'Regression', cls: 'text-redpen' },
}

/** Deliberately difficult cases, run live through the real rules and posting code. */
export function AdversarialView() {
  const [suite, setSuite] = useState<AdvSuite | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')

  const run = useCallback(() => {
    setRunning(true)
    api
      .adversarial()
      .then((s) => {
        setSuite(s)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setRunning(false))
  }, [])

  useEffect(run, [run])

  const shown = useMemo(() => {
    const cases = suite?.cases ?? []
    if (filter === 'got_in') return cases.filter((c) => c.verdict !== 'as_expected')
    if (filter === 'all') return cases
    return cases.filter((c) => c.area === filter)
  }, [suite, filter])

  const gaps = suite?.cases.filter((c) => c.verdict !== 'as_expected') ?? []

  return (
    <div className="rounded-lg bg-bench p-4 text-steel-2 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="max-w-2xl">
          <h2 className="font-cond text-3xl font-bold tracking-tight text-steel-3">Adversarial suite</h2>
          <p className="mt-1 text-steel">
            Cases built to break the checker: duplicates in disguise, the wrong supplier, confident misreads. Each one
            states what <em>should</em> happen, then runs through the same rules and posting code as the counter, in a
            throwaway ledger. Nothing here touches the shift log.
          </p>
        </div>
        {suite && (
          <div className="flex flex-wrap items-end gap-x-7 gap-y-3">
            <Score n={suite.counts.as_expected} label="as expected" tone="text-[#7fc79b]" />
            <Score n={suite.counts.known_gap} label="known gaps" tone="text-[#ff8a7a]" />
            <Score n={suite.counts.regression} label="regressions" tone={suite.counts.regression ? 'text-[#ff8a7a]' : 'text-steel'} />
            <div className="text-sm text-rail">
              <button
                type="button"
                onClick={run}
                disabled={running}
                className="mb-1 block cursor-pointer rounded border border-rail px-3 py-1 font-cond text-base font-semibold text-steel-3 hover:border-steel-3 disabled:cursor-wait disabled:opacity-60"
              >
                {running ? 'Running…' : 'Run again'}
              </button>
              {suite.total} cases · {(suite.ms / 1000).toFixed(1)} s
            </div>
          </div>
        )}
      </div>

      {error && <p className="mt-4 rounded bg-bench-2 p-3 text-[#ff8a7a]">Could not run the suite: {error}</p>}

      {suite && gaps.length > 0 && (
        <section aria-label="What got through" className="mt-6 border-l-4 border-[#ff8a7a] bg-bench-2 px-4 py-3">
          <p className="font-cond text-lg font-semibold text-steel-3">
            {suite.got_in} of {suite.total} attempts got into the system when they shouldn't have
          </p>
          <ul className="mt-1 space-y-0.5 text-sm">
            {gaps.map((c) => (
              <li key={c.id}>
                <a href={`#adv-${c.id}`} className="underline decoration-rail underline-offset-2 hover:text-steel-3">
                  <b className="font-semibold text-steel-3">{c.id}</b> {c.title}
                </a>
                <span className="text-rail"> · {OUTCOME[c.actual.outcome].toLowerCase()}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {suite && (
        <div role="radiogroup" aria-label="Show" className="mt-6 flex flex-wrap gap-2">
          {(
            [
              ['all', `All ${suite.total}`],
              ['got_in', `Got in (${gaps.length})`],
              ['receiving', 'Receiving'],
              ['slips', 'Slips'],
            ] as const
          ).map(([v, label]) => (
            <button
              key={v}
              type="button"
              role="radio"
              aria-checked={filter === v}
              onClick={() => setFilter(v)}
              className={`cursor-pointer rounded-full px-3 py-1 font-cond text-base font-semibold ${
                filter === v ? 'bg-manila text-graphite' : 'bg-bench-2 text-steel hover:text-steel-3'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {!suite && !error && <p className="mt-6 text-rail">Running the cases…</p>}

      <div className={`mt-5 grid gap-5 xl:grid-cols-2 ${running ? 'opacity-60' : ''}`}>
        {shown.map((c) => (
          <Tag key={c.id} c={c} />
        ))}
      </div>
    </div>
  )
}

function Score({ n, label, tone }: { n: number; label: string; tone: string }) {
  return (
    <div className="leading-none">
      <div className={`font-cond text-5xl font-bold ${tone}`}>{n}</div>
      <div className="mt-1 text-sm text-steel">{label}</div>
    </div>
  )
}

function Tag({ c }: { c: AdvCase }) {
  const v = VERDICT[c.verdict]
  const outcomeMatch = c.actual.outcome === c.expect || (c.expect === 'blocked' && STOPS.has(c.actual.outcome))
  return (
    <article id={`adv-${c.id}`} className="tag relative scroll-mt-6 px-5 pt-5 pb-5 text-graphite sm:px-7">
      <div className="flex items-start gap-4">
        <span className="tag-hole mt-1 shrink-0" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 text-sm text-form-ink">
            <span className="font-cond text-xl font-bold text-graphite">{c.id}</span>
            <span className="tracking-wide uppercase">{c.area === 'receiving' ? 'Receiving' : 'Checkout slips'}</span>
          </div>
          <h3 className="mt-0.5 pr-24 font-cond text-xl leading-tight font-bold sm:pr-32">{c.title}</h3>
        </div>
      </div>
      <div
        className={`stamp absolute top-5 right-4 rounded-sm px-2 py-0.5 font-cond text-sm font-bold tracking-wider uppercase sm:right-6 sm:text-base ${v.cls} ${
          c.verdict === 'regression' ? 'bg-redpen !text-manila' : ''
        }`}
      >
        {v.label}
      </div>

      <p className="mt-3 text-graphite-2">{c.attempt}</p>

      <ol className="mt-3 space-y-1 border-t border-dashed border-manila-deep pt-3 text-sm">
        {c.setup.map((s, i) => (
          <li key={i} className="flex gap-2">
            <span className="w-5 shrink-0 font-semibold text-form-ink">{i + 1}.</span>
            <span>
              {s.say} <span className="text-form-ink">({OUTCOME[s.outcome].toLowerCase()})</span>
            </span>
          </li>
        ))}
        <li className="flex gap-2 font-semibold">
          <span className="w-5 shrink-0 text-form-ink">{c.setup.length + 1}.</span>
          <span>{c.attempt_step}</span>
        </li>
      </ol>

      <div className="mt-4 grid gap-px overflow-hidden rounded-sm bg-manila-deep sm:grid-cols-2">
        <Side
          head="Should"
          outcome={c.expect}
          codes={c.expect_codes}
          note={c.why}
        />
        <Side
          head="Did"
          outcome={c.actual.outcome}
          codes={c.actual.codes}
          wrong={!outcomeMatch}
          mustHave={c.expect_codes}
        />
      </div>

      {c.actual.message && (
        <p className="mt-3 text-sm">
          <span className="text-form-ink">The counter said: </span>
          <span className={`font-hand text-base leading-snug ${STOPS.has(c.actual.outcome) ? 'text-redpen' : 'text-amber'}`}>
            {c.actual.message}
          </span>
        </p>
      )}

      {c.known_gap && (
        <div className="mt-3 border-l-4 border-redpen bg-[#f3e6c4] px-3 py-2 text-sm">
          <b className="font-semibold text-redpen">Why it got in, and what would close it. </b>
          {c.known_gap}
        </div>
      )}
      {c.history && (
        <div className="mt-3 border-l-4 border-stamp bg-[#f3e6c4] px-3 py-2 text-sm">
          <b className="font-semibold text-stamp">Found by this suite. </b>
          {c.history}
        </div>
      )}
    </article>
  )
}

function Side({
  head,
  outcome,
  codes,
  note,
  wrong = false,
  mustHave = [],
}: {
  head: string
  outcome: AdvOutcome
  codes: string[]
  note?: string
  wrong?: boolean
  mustHave?: string[]
}) {
  return (
    <div className="bg-[#f1e3bd] p-3">
      <div className="text-xs font-semibold tracking-widest text-form-ink uppercase">{head}</div>
      <div className={`mt-0.5 font-cond text-lg leading-tight font-semibold ${wrong ? 'text-redpen' : ''}`}>
        {OUTCOME[outcome]}
      </div>
      {codes.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {codes.map((code) => (
            <code
              key={code}
              className={`rounded-sm px-1.5 py-0.5 text-[0.7rem] font-semibold ${
                mustHave.includes(code) ? 'bg-graphite text-manila' : 'bg-manila-deep/50 text-graphite-2'
              }`}
            >
              {code}
            </code>
          ))}
        </div>
      )}
      {note && <p className="mt-1.5 text-sm text-graphite-2">{note}</p>}
    </div>
  )
}
