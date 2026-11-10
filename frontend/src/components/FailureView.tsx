import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Fate, FailureAnalysis, FailureGroup, Prop, Slip } from '../types'
import { EvalInspector, type InspectTarget } from './EvalInspector'

const FATE: Record<Fate, { label: string; swatch: string; text: string }> = {
  stopped: { label: 'Stopped (review or block)', swatch: 'bg-mark-ok', text: 'text-stamp' },
  warned_only: { label: 'Warned only (still posts)', swatch: 'bg-mark-warn', text: 'text-amber' },
  nothing_raised: { label: 'Nothing raised', swatch: 'hatch-bad', text: 'text-redpen' },
}
const FATES: Fate[] = ['stopped', 'warned_only', 'nothing_raised']

const pct = (p: Prop) => (p.rate === null ? 'n/a' : `${Math.round(p.rate * 100)}%`)
const frac = (p: { k: number; n: number }) => `${p.k}/${p.n}`

/** Where reading + rules go wrong, from the saved evaluation results. Nothing is re-run. */
export function FailureView({
  onAdversarial,
  onOpenInCounter,
}: {
  onAdversarial: () => void
  onOpenInCounter: (name: string, slip: Slip, photo: string) => void
}) {
  const [split, setSplit] = useState('heldout_corrected')
  const [inspect, setInspect] = useState<InspectTarget | null>(null)
  const [data, setData] = useState<FailureAnalysis | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    api
      .failures(split)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [split])

  if (error && !data) return <p className="text-redpen">Could not load the failure analysis: {error}</p>
  if (!data) return <p className="text-graphite-2">Loading the evaluation results…</p>
  const t = data.tiles

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h2 className="font-cond text-3xl font-bold tracking-tight">Failure analysis</h2>
          <p className="mt-1 text-graphite-2">
            Where photo reading plus rules goes wrong on handwritten slips, field by field. Built from the saved
            evaluation results ({data.source}
            {data.commit ? `, commit ${data.commit.slice(0, 7)}` : ''}); nothing is re-run and no model is called.
          </p>
        </div>
        <div role="radiogroup" aria-label="Which results" className="flex flex-wrap gap-1 rounded-md bg-steel-2 p-1">
          {data.splits.map((s) => (
            <button
              key={s.key}
              type="button"
              role="radio"
              aria-checked={split === s.key}
              onClick={() => setSplit(s.key)}
              className={`cursor-pointer rounded px-3 py-1 font-cond text-base font-semibold ${
                split === s.key ? 'bg-graphite text-steel-3' : 'text-graphite-2 hover:text-graphite'
              }`}
            >
              {s.title}
            </button>
          ))}
        </div>
      </header>

      {data.note && (
        <p className="max-w-3xl rounded-md border-l-4 border-amber bg-steel-3 px-4 py-2 text-sm">
          <b>Rules {data.ruleset}. </b>
          {data.note}
        </p>
      )}
      {!data.note && (
        <p className="text-sm text-graphite-2">
          Scored with rules {data.ruleset}, {data.ruleset === 'v1' ? 'the rules frozen for the evaluation' : 'the current rules'}.
        </p>
      )}

      <section aria-label="Headline numbers" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Tile
          value={frac(t.posting_wrong_critical)}
          label="slips that would post a wrong critical value"
          note={`95% interval ${Math.round(t.posting_wrong_critical.ci95[0] * 100)}–${Math.round(t.posting_wrong_critical.ci95[1] * 100)}%`}
          bad={t.posting_wrong_critical.k > 0}
        />
        <Tile value={frac(t.posting_wrong_any)} label="slips that would post any wrong value" note="names, dates and places included" bad={t.posting_wrong_any.k > 0} />
        <Tile
          value={frac(t.person_needed)}
          label="slips that needed a person"
          note={`${frac(t.slips_reviewed)} for a low-confidence read; the rest for a block a correct reading wouldn't have`}
          bad={false}
        />
        <Tile
          value={frac(t.confident_wrong)}
          label="fields read at 0.90+ that were wrong"
          note="confidence alone would pass these"
          bad={t.confident_wrong.k > 0}
        />
      </section>

      <section aria-label="Where it fails, in 30 seconds" className="max-w-4xl rounded-md bg-graphite px-5 py-4 text-steel-2">
        <h3 className="font-cond text-lg font-bold text-steel-3">Where it fails, in 30 seconds</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {data.findings.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
        <p className="mt-2 text-sm text-rail">
          "Would be posted": wrong, written into the posted entry, and not stopped. A warning is not a stop. Assumes the
          clerk settles every stop correctly from the paper.
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="What gets misread, and what happened to it" sub="Wrong reads per field, split by what the checker did about them.">
          <FieldBars rows={data.by_field} />
        </Panel>

        <Panel
          title="Confidence vs correctness"
          sub={`Every scored field by the model's own confidence. Below ${data.confidence.threshold.toFixed(2)} a person checks the paper.`}
        >
          <ConfidenceChart c={data.confidence} />
        </Panel>

        <Panel
          title="Misses: wrong values nothing stopped"
          sub="Sorted: what would be posted first. A description next to a part number is not stored (the entry uses the catalog name)."
          wide
        >
          <MissTable rows={data.misses} kinds={data.miss_kinds} onInspect={(r) => setInspect({ split, slip: r.slip, name: r.name, line: r.line })} />
        </Panel>

        <Panel
          title="False positives: correct reads that were flagged"
          sub={`${data.false_positive_totals.reviews + data.false_positive_totals.rule_blocks} stopped someone (${data.false_positive_totals.reviews} low-confidence reviews, ${data.false_positive_totals.rule_blocks} rule blocks). ${data.false_positive_totals.rule_warnings} more were only warnings, which don't stop posting.`}
        >
          <FalsePositives rows={data.false_positives} />
        </Panel>

        <Panel title="Human review frequency" sub="Review requests per slip. Each one is a person checking the paper.">
          <ReviewChart h={data.reviews.histogram} perSlip={data.reviews.per_slip} />
        </Panel>

        <Panel title="By handwriting style" sub="One writer in four deliberate styles: direction, not measurement.">
          <GroupTable rows={data.by_style} head="Style" />
        </Panel>

        <Panel title="By photo condition" sub="Conditions were assigned when the slips were written.">
          <GroupTable rows={data.by_condition} head="Condition" />
        </Panel>

        <Panel title="By document type" sub="Only one document type has a labelled evaluation.">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-rail/60 text-left text-graphite-2">
                <th className="py-1.5 pr-3 font-semibold">Document</th>
                <th className="py-1.5 pr-3 font-semibold">Reading accuracy</th>
                <th className="py-1.5 font-semibold">Rules</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-rail/30 align-top">
                <td className="py-2 pr-3 font-semibold">Handwritten checkout slip (photo)</td>
                <td className="py-2 pr-3">Evaluated: {t.slips} slips in this view</td>
                <td className="py-2">Evaluated with the reading, above</td>
              </tr>
              <tr className="align-top">
                <td className="py-2 pr-3 font-semibold">Delivery receipt (PDF or photo)</td>
                <td className="py-2 pr-3 text-redpen">
                  Not evaluated. 12 PDFs are read from the text layer (exact by construction); 1 photo; no labelled set.
                </td>
                <td className="py-2">
                  <button type="button" onClick={onAdversarial} className="cursor-pointer underline">
                    Adversarial suite
                  </button>{' '}
                  (8 receipt cases)
                </td>
              </tr>
            </tbody>
          </table>
        </Panel>
      </div>
      {inspect && (
        <EvalInspector
          target={inspect}
          onClose={() => setInspect(null)}
          onOpenInCounter={(name, slip, photo) => {
            setInspect(null)
            onOpenInCounter(name, slip, photo)
          }}
        />
      )}
    </div>
  )
}

function Tile({ value, label, note, bad }: { value: string; label: string; note: string; bad: boolean }) {
  return (
    <div className="rounded-md border border-rail/50 bg-steel-3 px-4 py-3">
      <div className={`font-cond text-4xl font-bold ${bad ? 'text-redpen' : 'text-graphite'}`}>{value}</div>
      <div className="mt-0.5 font-semibold leading-snug">{label}</div>
      <div className="text-sm text-graphite-2">{note}</div>
    </div>
  )
}

function Panel({ title, sub, wide, children }: { title: string; sub: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <section className={`min-w-0 rounded-md bg-steel-3 p-4 sm:p-5 ${wide ? 'xl:col-span-2' : ''}`}>
      <h3 className="font-cond text-xl font-bold">{title}</h3>
      <p className="mt-0.5 mb-4 text-sm text-graphite-2">{sub}</p>
      {children}
    </section>
  )
}

function Legend() {
  return (
    <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-graphite-2">
      {FATES.map((f) => (
        <span key={f} className="inline-flex items-center gap-1.5">
          <span className={`inline-block size-3 rounded-sm ${FATE[f].swatch}`} aria-hidden />
          {FATE[f].label}
        </span>
      ))}
    </div>
  )
}

function FieldBars({ rows }: { rows: FailureAnalysis['by_field'] }) {
  const max = Math.max(1, ...rows.map((r) => r.wrong))
  return (
    <div>
      <Legend />
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.field} className="grid grid-cols-[7.5rem_minmax(0,1fr)_5.5rem] items-center gap-2 text-sm">
            <span className="truncate font-semibold" title={r.critical === 'no' ? '' : `Critical: ${r.critical}`}>
              {r.label}
              {r.critical === 'always' && <span className="ml-1 text-xs font-normal text-graphite-2">critical</span>}
            </span>
            <span
              className="flex h-4 gap-[2px]"
              role="img"
              aria-label={`${r.label}: ${r.wrong} wrong of ${r.fields}; ${r.stopped} stopped, ${r.warned_only} warned only, ${r.nothing_raised} nothing raised`}
            >
              {r.wrong === 0 && <span className="h-full w-px bg-rail/60" />}
              {FATES.map((f) =>
                r[f] ? (
                  <span
                    key={f}
                    title={`${FATE[f].label}: ${r[f]}`}
                    className={`h-full first:rounded-l last:rounded-r ${FATE[f].swatch}`}
                    style={{ width: `${(r[f] / max) * 100}%` }}
                  />
                ) : null,
              )}
            </span>
            <span className="text-right text-graphite-2">
              <b className="text-graphite">{r.wrong}</b> of {r.fields}
              {r.posted > 0 && <span className="block text-xs text-redpen">{r.posted} would post</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ConfidenceChart({ c }: { c: FailureAnalysis['confidence'] }) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...c.bins.map((b) => b.correct + b.wrong))
  const H = 160
  const thresholdAt = c.bins.findIndex((b) => b.from >= c.threshold)
  const h = hover === null ? null : c.bins[hover]
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-x-4 text-sm text-graphite-2">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-mark-ok" aria-hidden /> Read correctly
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm hatch-bad" aria-hidden /> Read wrong
        </span>
      </div>
      <div className="relative">
        <div className="flex items-end gap-1 border-b border-rail" style={{ height: H }} onMouseLeave={() => setHover(null)}>
          {c.bins.map((b, i) => {
            const total = b.correct + b.wrong
            return (
              <div
                key={b.from}
                className="relative flex h-full flex-1 cursor-default flex-col justify-end"
                onMouseEnter={() => setHover(i)}
                role="img"
                aria-label={`${b.from.toFixed(2)} to ${b.to.toFixed(2)}: ${b.correct} correct, ${b.wrong} wrong`}
              >
                {i === thresholdAt && (
                  <span className="absolute -left-[3px] top-0 bottom-0 border-l-2 border-dashed border-graphite" aria-hidden />
                )}
                {b.wrong > 0 && (
                  <span className="mb-0.5 text-center text-xs font-semibold text-redpen">{b.wrong}</span>
                )}
                <span className="flex flex-col gap-[2px]">
                  {b.wrong > 0 && <span className="hatch-bad rounded-t" style={{ height: (b.wrong / max) * (H - 18) }} />}
                  {b.correct > 0 && (
                    <span
                      className={`bg-mark-ok ${b.wrong ? '' : 'rounded-t'}`}
                      style={{ height: (b.correct / max) * (H - 18) }}
                    />
                  )}
                </span>
                {hover === i && total > 0 && <span className="pointer-events-none absolute inset-0 bg-graphite/5" />}
              </div>
            )
          })}
        </div>
        <div className="mt-1 flex gap-1 text-[0.7rem] text-graphite-2">
          {c.bins.map((b) => (
            <span key={b.from} className="flex-1 text-center">
              {b.from.toFixed(2)}
            </span>
          ))}
        </div>
      </div>
      <p className="mt-2 min-h-5 text-sm">
        {h ? (
          <>
            Confidence {h.from.toFixed(2)}–{h.to.toFixed(2)}: <b>{h.correct}</b> correct, <b className="text-redpen">{h.wrong}</b>{' '}
            wrong{h.from >= c.threshold ? ' (not sent to review)' : ' (sent to review)'}.
          </>
        ) : (
          <span className="text-graphite-2">
            Dashed line: the 0.75 review threshold. Hover a column for its counts. Wrong reads to the right of the line
            were trusted.
          </span>
        )}
      </p>
    </div>
  )
}

function MissTable({
  rows,
  kinds,
  onInspect,
}: {
  rows: FailureAnalysis['misses']
  kinds: FailureAnalysis['miss_kinds']
  onInspect: (r: FailureAnalysis['misses'][number]) => void
}) {
  if (!rows.length) return <p className="text-graphite-2">Every wrong value was stopped.</p>
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2 text-sm">
        {kinds.map((k) => (
          <span key={k.kind} className="rounded-full bg-steel-2 px-2.5 py-0.5">
            {k.kind} <b>{k.count}</b>
          </span>
        ))}
      </div>
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[46rem] text-sm">
          <thead>
            <tr className="border-b border-rail/60 text-left text-graphite-2">
              <th className="py-1.5 pr-3 font-semibold">Slip</th>
              <th className="py-1.5 pr-3 font-semibold">Field</th>
              <th className="py-1.5 pr-3 font-semibold">Paper says</th>
              <th className="py-1.5 pr-3 font-semibold">Read as</th>
              <th className="py-1.5 pr-3 text-right font-semibold">Conf.</th>
              <th className="py-1.5 pr-3 font-semibold">Checker</th>
              <th className="py-1.5 pr-3 font-semibold">Kind</th>
              <th className="py-1.5 pr-3 font-semibold">Posted?</th>
              <th className="py-1.5 font-semibold">
                <span className="sr-only">Evidence</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.slip}-${r.field}-${r.line}`} className={`border-b border-rail/30 ${r.posted ? '' : 'text-graphite-2'}`}>
                <td className="py-1.5 pr-3">
                  {r.slip} <span className="text-xs text-graphite-2">{r.style}</span>
                </td>
                <td className="py-1.5 pr-3">
                  {r.field}
                  {r.line ? ` (line ${r.line})` : ''}
                  {r.critical && <span className="ml-1 text-xs font-semibold text-redpen">critical</span>}
                </td>
                <td className="py-1.5 pr-3 font-hand text-base text-ballpoint">{r.paper || '(blank)'}</td>
                <td className="py-1.5 pr-3 font-hand text-base text-redpen">{r.read || '(blank)'}</td>
                <td className="py-1.5 pr-3 text-right">{r.confidence?.toFixed(2) ?? '–'}</td>
                <td className={`py-1.5 pr-3 ${FATE[r.fate].text}`}>{r.fate === 'warned_only' ? 'warned only' : 'nothing raised'}</td>
                <td className="py-1.5 pr-3">{r.kind}</td>
                <td className="py-1.5 pr-3 font-semibold">{r.posted ? <span className="text-redpen">yes</span> : 'no, not stored'}</td>
                <td className="py-1.5">
                  <button
                    type="button"
                    onClick={() => onInspect(r)}
                    className="cursor-pointer rounded border border-graphite/30 bg-white px-2 py-0.5 text-xs font-semibold text-graphite hover:border-graphite"
                    aria-label={`Inspect ${r.slip} ${r.field}: photo and evidence`}
                  >
                    Inspect
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function FalsePositives({ rows }: { rows: FailureAnalysis['false_positives'] }) {
  if (!rows.length) return <p className="text-graphite-2">No correctly read field was flagged.</p>
  const max = Math.max(1, ...rows.map((r) => r.reviews + r.rule_blocks + r.rule_warnings))
  const SERIES = [
    { key: 'reviews', label: 'Review (stops posting)', cls: 'bg-graphite' },
    { key: 'rule_blocks', label: 'Rule block (stops posting)', cls: 'bg-mark-bad' },
    { key: 'rule_warnings', label: "Warning only (doesn't stop)", cls: 'bg-mark-warn' },
  ] as const
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-graphite-2">
        {SERIES.map((x) => (
          <span key={x.key} className="inline-flex items-center gap-1.5">
            <span className={`inline-block size-3 rounded-sm ${x.cls}`} aria-hidden /> {x.label}
          </span>
        ))}
      </div>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.field} className="grid grid-cols-[7.5rem_minmax(0,1fr)_6rem] items-center gap-2 text-sm">
            <span className="font-semibold">{r.label}</span>
            <span
              className="flex h-4 gap-[2px]"
              role="img"
              aria-label={`${r.label}: ${r.reviews} reviews, ${r.rule_blocks} rule blocks, ${r.rule_warnings} warnings`}
            >
              {SERIES.map((x) =>
                r[x.key] > 0 ? (
                  <span
                    key={x.key}
                    title={`${x.label}: ${r[x.key]}`}
                    className={`h-full first:rounded-l last:rounded-r ${x.cls}`}
                    style={{ width: `${(r[x.key] / max) * 100}%` }}
                  />
                ) : null,
              )}
            </span>
            <span className="text-right text-graphite-2">
              {r.reviews} · {r.rule_blocks} · {r.rule_warnings}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-sm text-graphite-2">
        Counts are review · block · warning. A rule flag on a correctly read field usually comes from a misread
        elsewhere on the slip (a W/O checked against a misread name). Under rules v2, quantity confirmations are rule
        blocks on correctly read quantities: that is their cost.
      </p>
    </div>
  )
}

function ReviewChart({ h, perSlip }: { h: FailureAnalysis['reviews']['histogram']; perSlip: FailureAnalysis['reviews']['per_slip'] }) {
  const max = Math.max(1, ...h.map((x) => x.slips))
  return (
    <div>
      <ul className="space-y-2">
        {h.map((x) => (
          <li key={x.reviews} className="grid grid-cols-[7.5rem_minmax(0,1fr)_3rem] items-center gap-2 text-sm">
            <span className="font-semibold">
              {x.reviews === 3 ? '3 or more' : x.reviews} review{x.reviews === 1 ? '' : 's'}
            </span>
            <span className="h-4">
              <span className="block h-full rounded bg-graphite" style={{ width: `${(x.slips / max) * 100}%` }} />
            </span>
            <span className="text-right">
              <b>{x.slips}</b> slips
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap gap-1.5" aria-label="Reviews per slip">
        {perSlip.map((p) => (
          <span
            key={p.slip}
            title={`${p.slip}: ${p.reviews} review${p.reviews === 1 ? '' : 's'}, ${p.needless} on correct reads, ${p.posted_wrong} wrong value(s) would post`}
            className={`rounded px-1.5 py-0.5 text-xs font-semibold ${
              p.reviews ? 'bg-graphite text-steel-3' : 'bg-steel-2 text-graphite-2'
            } ${p.posted_wrong ? 'ring-2 ring-redpen ring-offset-1 ring-offset-steel-3' : ''}`}
          >
            {p.slip} · {p.reviews}
          </span>
        ))}
      </div>
      <p className="mt-2 text-sm text-graphite-2">Red ring: the slip would still post a wrong value.</p>
    </div>
  )
}

function GroupTable({ rows, head }: { rows: FailureGroup[]; head: string }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-rail/60 text-left text-graphite-2">
          <th className="py-1.5 pr-3 font-semibold">{head}</th>
          <th className="py-1.5 pr-3 text-right font-semibold">Slips</th>
          <th className="py-1.5 pr-3 text-right font-semibold">Fields correct</th>
          <th className="py-1.5 pr-3 text-right font-semibold">Needed review</th>
          <th className="py-1.5 text-right font-semibold">Would post wrong</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className="border-b border-rail/30">
            <td className="py-1.5 pr-3">{r.label}</td>
            <td className="py-1.5 pr-3 text-right">{r.slips}</td>
            <td className="py-1.5 pr-3 text-right">
              {frac(r.fields_correct)} <span className="text-graphite-2">({pct(r.fields_correct)})</span>
            </td>
            <td className="py-1.5 pr-3 text-right">{r.slips_reviewed}</td>
            <td className={`py-1.5 text-right ${r.slips_posting_wrong ? 'font-semibold text-redpen' : ''}`}>
              {r.slips_posting_wrong}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
