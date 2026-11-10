import { useEffect, useState } from 'react'
import { api } from '../api'
import { whereLabel } from '../slip'
import type { EvalSlipDetail, Evidence, Issue, Slip } from '../types'

const EXTRA_PINS: Record<string, string[]> = {
  NAME_NUMBER_MISMATCH: ['part_name'],
  UNIT_AMBIGUOUS: ['qty'], UNIT_REMAINDER: ['qty'], UNIT_ASSUMED: ['qty'], UNIT_MISMATCH: ['qty'], UNIT_CONVERTED: ['qty'],
  LOCATION_MISMATCH: ['wo_number'], NOT_ON_CREW: ['wo_number'], BEFORE_WO_OPENED: ['wo_number'],
}

export interface InspectTarget {
  split: string
  slip: string
  name: string // field key, e.g. taken_by, qty
  line: number | null
}

/**
 * Drill-down from a failure-analysis row to the original evidence: the photo the reading came from,
 * the value read and where it came from, the answer key, and what the checker raised on that field.
 */
export function EvalInspector({
  target,
  onClose,
  onOpenInCounter,
}: {
  target: InspectTarget
  onClose: () => void
  onOpenInCounter: (name: string, slip: Slip, photo: string) => void
}) {
  const [detail, setDetail] = useState<EvalSlipDetail | null>(null)
  const [checked, setChecked] = useState<{ issues: Issue[]; evidence: Evidence[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [big, setBig] = useState(false)

  useEffect(() => {
    let alive = true
    setDetail(null)
    setChecked(null)
    api
      .evalSlip(target.split, target.slip)
      .then(async (d) => {
        if (!alive) return
        setDetail(d)
        // The same rule set the results were scored with; not recorded in the shift log.
        const r = await api.validateWith(d.reading, d.ruleset)
        if (alive) setChecked({ issues: r.issues, evidence: r.evidence ?? [] })
      })
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [target.split, target.slip])

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const field = detail?.fields.find((f) => f.name === target.name && (f.line ?? null) === target.line)
  // Same pins as the evaluation (eval.py EXTRA_PINS): an issue can be about more than its own field.
  const onField = (i: Issue) => i.line === target.line && (i.key === target.name || (EXTRA_PINS[i.code] ?? []).includes(target.name))
  const here = checked ? checked.issues.map((i, n) => ({ i, e: checked.evidence[n] })).filter(({ i }) => onField(i)) : []
  const elsewhere = checked ? checked.issues.filter((i) => !onField(i) && i.severity !== 'info') : []

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-graphite/40" role="dialog" aria-modal="true" aria-label={`Inspect ${target.slip}`} onClick={onClose}>
      <div className="h-full w-full max-w-2xl overflow-y-auto bg-steel-3 p-5 shadow-2xl sm:p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-cond text-2xl font-bold">
              {target.slip}
              {field && <span className="font-semibold text-graphite-2">, {whereLabel(target.line ? `line ${target.line} ${target.name}` : target.name)}</span>}
            </h2>
            {detail && (
              <p className="text-sm text-graphite-2">
                Style {detail.style} · {detail.condition} · scored with rules {detail.ruleset}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} className="cursor-pointer rounded border border-rail px-2.5 py-1 text-sm hover:border-graphite">
            Close
          </button>
        </div>

        {error && <p className="mt-4 text-redpen">Could not load this slip: {error}</p>}
        {!detail && !error && <p className="mt-4 text-graphite-2">Loading the photo and the reading…</p>}

        {detail && (
          <div className="mt-4 space-y-5 text-sm">
            <section>
              <h3 className="mb-1 font-cond text-lg font-bold">The photo this reading came from</h3>
              <button type="button" onClick={() => setBig((b) => !b)} className="block cursor-zoom-in" aria-label="Enlarge the photo">
                <img
                  src={detail.photo}
                  alt={`Photo of slip ${detail.photo_of}`}
                  className={`rounded border border-rail bg-white ${big ? 'w-full' : 'max-h-72'}`}
                />
              </button>
              <p className="mt-1 text-graphite-2">
                {detail.photo_of !== detail.slip
                  ? `This is ${detail.photo_of}'s file: the photos for ${detail.slip} and ${detail.photo_of} were saved under each other's names, and this view uses the recorded correction.`
                  : detail.swapped
                    ? `This file is filed as ${detail.slip} but shows another slip (the recorded photo swap); the locked view scores it as it was filed.`
                    : `${detail.reading._provenance && typeof detail.reading._provenance === 'object' ? 'Read by a vision model, which gives no position on the page: ' : ''}${target.line ? `line ${target.line} of the slip.` : 'the slip header.'} Click to enlarge.`}
              </p>
            </section>

            {field && (
              <section className="rounded-md bg-white p-3">
                <h3 className="mb-1 font-cond text-lg font-bold">The field</h3>
                <table className="w-full">
                  <tbody>
                    <Row k="Paper says (answer key)">
                      <span className="font-hand text-lg text-ballpoint">{field.truth || '(blank)'}</span>
                    </Row>
                    <Row k="Read as">
                      <span className={`font-hand text-lg ${field.correct ? 'text-ballpoint' : 'text-redpen'}`}>{field.read || '(blank)'}</span>
                      {!field.correct && <span className="ml-2 font-semibold text-redpen">wrong</span>}
                    </Row>
                    <Row k="Model's confidence">{field.confidence?.toFixed(2) ?? '–'}</Row>
                    <Row k="Source">
                      {field.source
                        ? `${field.source.document}${field.source.line ? `, line ${field.source.line}` : ''} · ${field.source.method}${field.source.model ? ` (${field.source.model})` : ''}`
                        : 'not recorded'}
                    </Row>
                    <Row k="Critical field">{field.critical ? 'yes' : 'no'}</Row>
                  </tbody>
                </table>
              </section>
            )}

            <section>
              <h3 className="mb-1 font-cond text-lg font-bold">What the checker raised on this field</h3>
              {!checked ? (
                <p className="text-graphite-2">Running the rules on the reading…</p>
              ) : here.length ? (
                <ul className="space-y-2">
                  {here.map(({ i, e }) => (
                    <li key={i.code + i.where} className={`rounded-md border-l-4 bg-white px-3 py-2 ${i.severity === 'block' ? 'border-redpen' : 'border-amber'}`}>
                      <p>
                        <code className="rounded-sm bg-steel-2 px-1 text-xs font-semibold">{i.code}</code> {i.message}
                      </p>
                      {e?.rule.text && <p className="mt-0.5 text-graphite-2">Rule: {e.rule.text}</p>}
                      <p className="mt-0.5 font-semibold">{e?.rule.outcome}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="font-semibold text-redpen">
                  Nothing. No rule fired on this field and the read was trusted, which is why the wrong value would be posted.
                </p>
              )}
              {checked && elsewhere.length > 0 && (
                <p className="mt-2 text-graphite-2">
                  Elsewhere on this slip: {elsewhere.map((i) => `${whereLabel(i.where)} ${i.code}`).join('; ')}.
                </p>
              )}
            </section>

            <section>
              <h3 className="mb-1 font-cond text-lg font-bold">Every scored field on this slip</h3>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-rail/60 text-left text-graphite-2">
                    <th className="py-1 pr-2 font-semibold">Field</th>
                    <th className="py-1 pr-2 font-semibold">Paper</th>
                    <th className="py-1 pr-2 font-semibold">Read</th>
                    <th className="py-1 text-right font-semibold">Conf.</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.fields.map((f) => {
                    const on = f.name === target.name && (f.line ?? null) === target.line
                    return (
                      <tr key={`${f.line}-${f.name}`} className={`border-b border-rail/30 ${on ? 'bg-amber/10 font-semibold' : ''}`}>
                        <td className="py-1 pr-2">{whereLabel(f.line ? `line ${f.line} ${f.name}` : f.name)}</td>
                        <td className="py-1 pr-2">{f.truth || '–'}</td>
                        <td className={`py-1 pr-2 ${f.correct ? '' : 'text-redpen'}`}>{f.read || '–'}</td>
                        <td className="py-1 text-right">{f.confidence?.toFixed(2) ?? '–'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </section>

            <button
              type="button"
              onClick={() => onOpenInCounter(`${target.slip} (evaluation)`, detail.reading, detail.photo)}
              className="w-full cursor-pointer rounded-md bg-graphite px-4 py-2.5 font-cond text-lg font-semibold text-steel-3 hover:bg-graphite-2"
            >
              Open this reading in the Counter (current rules)
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <tr className="border-b border-rail/30 align-top">
      <td className="w-[40%] py-1 pr-3 text-graphite-2">{k}</td>
      <td className="py-1">{children}</td>
    </tr>
  )
}
