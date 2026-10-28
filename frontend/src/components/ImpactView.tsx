import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Impact, Range } from '../types'

interface Input {
  key: string
  label: string
  min: number
  max: number
  step: number
  show: (v: number) => string
}

const pct = (v: number) => `${Math.round(v * 100)}%`
const INPUTS: Input[] = [
  { key: 'slip_caused_share', label: 'Mismatches that start as a slip error', min: 0, max: 1, step: 0.01, show: pct },
  { key: 'slips_per_week', label: 'Slips per week', min: 10, max: 250, step: 5, show: (v) => `${v}` },
  { key: 'mismatches_per_week', label: 'Count mismatches per week', min: 1, max: 20, step: 0.5, show: (v) => `${v}` },
  { key: 'minutes_per_mismatch', label: 'Minutes to chase one mismatch', min: 5, max: 120, step: 5, show: (v) => `${v} min` },
  { key: 'minutes_per_flag', label: 'Minutes to answer a flag at the counter', min: 1, max: 15, step: 0.5, show: (v) => `${v} min` },
  { key: 'seconds_added_per_slip', label: 'Seconds the check adds to every slip', min: 0, max: 60, step: 5, show: (v) => `${v} s` },
  { key: 'unresolved_share', label: 'Mismatches never traced (left for the audit)', min: 0, max: 1, step: 0.05, show: pct },
  { key: 'clerk_hourly_cost', label: 'Staff hourly cost', min: 10, max: 80, step: 1, show: (v) => `$${v}` },
]

const hours = (h: number) => `${h >= 0 ? '+' : '−'}${Math.abs(Math.round(h))}`
const money = (d: number) => `${d >= 0 ? '' : '−'}$${Math.abs(Math.round(d)).toLocaleString()}`
const one = (n: number) => (Math.round(n * 10) / 10).toString()

/** ESTIMATED value of the checker vs the manual process. Every number here is labeled. */
export function ImpactView() {
  const [result, setResult] = useState<Impact | null>(null)
  const [values, setValues] = useState<Record<string, number> | null>(null)
  const [defaults, setDefaults] = useState<Record<string, number> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    api
      .impact({})
      .then((r) => {
        setResult(r)
        setValues(r.likely_inputs)
        setDefaults(r.likely_inputs)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const change = (key: string, v: number) => {
    const next = { ...values, [key]: v }
    setValues(next)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      api.impact(next).then(setResult).catch((e: Error) => setError(e.message))
    }, 150)
  }

  if (error && !result) return <p className="text-redpen">Could not load the estimate: {error}</p>
  if (!result || !values || !defaults) return <p className="text-graphite-2">Running the checker on the test slips.</p>

  const { pessimistic: lo, likely: mid, optimistic: hi } = result.scenarios
  const ranges = result.assumptions as unknown as Record<string, Range>
  const share = values.slip_caused_share
  const be = mid.break_even_slip_share
  const pays = be !== null && share >= be
  const changed = INPUTS.some((i) => values[i.key] !== defaults[i.key])

  return (
    <div className="space-y-8">
      <div role="note" className="rounded-md border-l-4 border-amber bg-steel-3 px-4 py-3">
        <p className="font-semibold">Estimated, not measured.</p>
        <p className="mt-0.5 max-w-3xl text-sm text-graphite-2">
          Slips per week, mismatches per week and minutes per mismatch were observed in the storeroom. The rest are
          assumptions you can adjust below. Only the detection rates were measured, by running the real checker on{' '}
          {result.settings.n_per_type * Object.keys(result.detection).length} synthetic slips. A two-week pilot alongside the paper
          process would replace the estimates with real numbers.
        </p>
      </div>

      <section aria-live="polite" className="max-w-4xl">
        <p className="font-cond text-2xl leading-snug font-semibold sm:text-3xl">
          {mid.hours_per_year_saved >= 0 ? (
            <>
              With these assumptions the check saves an estimated{' '}
              <span className="text-stamp">{Math.round(mid.hours_per_year_saved)} staff hours a year</span> (about{' '}
              {money(mid.dollars_per_year_saved)}).
            </>
          ) : (
            <>
              With these assumptions the check costs an estimated{' '}
              <span className="text-redpen">{Math.round(-mid.hours_per_year_saved)} staff hours a year</span> more than
              it saves.
            </>
          )}
        </p>
        <p className="mt-2 text-lg text-graphite-2">
          {be === null ? (
            'It never pays off with these inputs.'
          ) : (
            <>
              It pays off as long as at least <b className="text-graphite">{pct(be)}</b> of count mismatches start as a slip
              error. You are assuming <b className={pays ? 'text-stamp' : 'text-redpen'}>{pct(share)}</b>.
            </>
          )}{' '}
          Across the worst and best end of every input at once, the estimate ranges from {hours(lo.hours_per_year_saved)} to{' '}
          {hours(hi.hours_per_year_saved)} hours a year.
        </p>
      </section>

      <div className="grid gap-8 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <section>
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="font-cond text-xl font-bold">Inputs</h2>
            {changed && (
              <button
                type="button"
                onClick={() => {
                  setValues(defaults)
                  api.impact(defaults).then(setResult)
                }}
                className="cursor-pointer text-sm underline"
              >
                Reset to the file’s values
              </button>
            )}
          </div>
          <ul className="mt-3 space-y-4">
            {INPUTS.map((i) => {
              const r = ranges[i.key]
              const id = `in-${i.key}`
              return (
                <li key={i.key}>
                  <div className="flex items-baseline justify-between gap-3">
                    <label htmlFor={id} className="text-[0.95rem]">
                      {i.label}{' '}
                      <span
                        title={r.basis}
                        className={`ml-1 rounded px-1.5 py-0.5 text-xs font-semibold ${
                          r.source === 'observed' ? 'bg-stamp/15 text-stamp' : 'bg-amber/15 text-amber'
                        }`}
                      >
                        {r.source === 'observed' ? 'Observed' : 'Assumed'}
                      </span>
                    </label>
                    <span className="font-semibold whitespace-nowrap">{i.show(values[i.key])}</span>
                  </div>
                  <div className="relative mt-1">
                    <input
                      id={id}
                      type="range"
                      min={i.min}
                      max={i.max}
                      step={i.step}
                      value={values[i.key]}
                      onChange={(e) => change(i.key, Number(e.target.value))}
                      className="w-full accent-graphite"
                    />
                    {i.key === 'slip_caused_share' && be !== null && be <= 1 && (
                      <div
                        aria-hidden
                        className="pointer-events-none absolute -bottom-4 -translate-x-1/2 text-xs font-semibold whitespace-nowrap text-stamp"
                        style={{ left: `${be * 100}%` }}
                      >
                        ▲ break-even {pct(be)}
                      </div>
                    )}
                  </div>
                  <p className={`text-xs text-graphite-2 ${i.key === 'slip_caused_share' ? 'mt-5' : 'mt-0.5'}`}>
                    {r.basis.replace(/\.$/, '')}. File range {i.show(r.low)} to {i.show(r.high)}.
                  </p>
                </li>
              )
            })}
          </ul>
        </section>

        <div className="space-y-8">
          <section>
            <h2 className="font-cond text-xl font-bold">Manual vs with the check (estimated)</h2>
            <table className="mt-2 w-full text-left text-sm">
              <thead className="text-graphite-2">
                <tr className="border-b border-rail/60">
                  <th className="py-1.5 pr-2 font-medium" />
                  <th className="py-1.5 pr-2 text-right font-medium">Manual</th>
                  <th className="py-1.5 pr-2 text-right font-medium">With check</th>
                  <th className="hidden py-1.5 text-right font-medium sm:table-cell">Worst to best case</th>
                </tr>
              </thead>
              <tbody>
                <Row label="Count mismatches per week" a={one(mid.mismatches_per_week.manual)} b={one(mid.mismatches_per_week.checked)}
                  range={`${one(lo.mismatches_per_week.checked)} to ${one(hi.mismatches_per_week.checked)}`} />
                <Row label="Staff hours per week" a={one(mid.hours_per_week.manual)} b={one(mid.hours_per_week.checked)}
                  range={`${one(lo.hours_per_week.checked)} to ${one(hi.hours_per_week.checked)}`} />
                <Row label="Flags answered at the counter per week" a="0" b={one(mid.flags_per_week)}
                  range={`${one(lo.flags_per_week)} to ${one(hi.flags_per_week)}`} />
                <Row label="Variances left for the yearly audit" a={Math.round(mid.audit_variances_per_year.manual).toString()}
                  b={Math.round(mid.audit_variances_per_year.checked).toString()}
                  range={`${Math.round(lo.audit_variances_per_year.checked)} to ${Math.round(hi.audit_variances_per_year.checked)}`} />
                <Row label="Corrections logged with their cause, per year" a="0" b={Math.round(mid.corrections_logged_per_year).toString()}
                  range={`${Math.round(lo.corrections_logged_per_year)} to ${Math.round(hi.corrections_logged_per_year)}`} />
                <Row label="Hours saved per year" a="" b={hours(mid.hours_per_year_saved)} strong
                  range={`${hours(lo.hours_per_year_saved)} to ${hours(hi.hours_per_year_saved)}`} />
              </tbody>
            </table>
            <p className="mt-2 text-xs text-graphite-2">
              The worst case puts every input at its worst end at the same time, so it is a floor, not a forecast. Staff
              time only; part prices and write-off value are not included yet.
            </p>
          </section>

          <section>
            <h2 className="font-cond text-xl font-bold">Measured: what the real rules caught</h2>
            <p className="mt-0.5 text-sm text-graphite-2">
              {result.settings.n_per_type} synthetic slips per error type, each with one error written in, run through the
              same checker the Counter uses.
            </p>
            <table className="mt-2 w-full text-left text-sm">
              <tbody>
                {Object.entries(result.detection).map(([k, d]) => (
                  <tr key={k} className="border-b border-rail/30">
                    <td className="py-1.5 pr-2">
                      {d.label}
                      {d.auto_ok > 0 && (
                        <span className="block text-xs text-graphite-2">
                          {pct(d.auto_ok / d.n)} matched automatically, {d.auto_wrong} matched to the wrong part
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 pr-2 text-right text-xs text-graphite-2">
                      {pct(result.assumptions.error_mix.shares[k])} of errors
                    </td>
                    <td className={`py-1.5 text-right font-semibold ${d.caught < 0.5 ? 'text-redpen' : ''}`}>{pct(d.caught)}</td>
                  </tr>
                ))}
                <tr>
                  <td className="py-1.5 pr-2 font-semibold">Weighted by the assumed error mix</td>
                  <td />
                  <td className="py-1.5 text-right font-semibold">{pct(mid.detection_weighted)}</td>
                </tr>
              </tbody>
            </table>
            <p className="mt-2 text-xs text-graphite-2">
              A wrong but plausible quantity contradicts nothing on the slip, so it is not caught, and the estimate does not
              count it. False alarms on clean synthetic slips: {pct(result.false_alarm_rate)}, which is likely too low for
              real handwriting.
            </p>
          </section>

          <section>
            <h2 className="font-cond text-xl font-bold">Left out on purpose</h2>
            <ul className="mt-2 space-y-2 text-sm">
              {Object.entries(result.assumptions.excluded).map(([k, v]) => (
                <li key={k}>
                  <span className="font-semibold">{k === 'cost_allocation' ? 'Who parts were charged to' : 'Receiving-document call-backs'}</span>
                  <span className="text-graphite-2"> ({v.source}). {v.basis}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </div>
  )
}

function Row({ label, a, b, range, strong = false }: { label: string; a: string; b: string; range: string; strong?: boolean }) {
  return (
    <tr className={`border-b border-rail/30 ${strong ? 'font-semibold' : ''}`}>
      <td className="py-1.5 pr-2">{label}</td>
      <td className="py-1.5 pr-2 text-right">{a}</td>
      <td className="py-1.5 pr-2 text-right">{b}</td>
      <td className="hidden py-1.5 text-right text-graphite-2 sm:table-cell">{range}</td>
    </tr>
  )
}
