import type { ShiftLog as Log } from '../types'
import { titleOf } from './Inbox'

/** Plain-language names for what was caught, for a supervisor reading the log. */
const CAUGHT_LABEL: Record<string, string> = {
  CLOSED_WO: 'Charged to a closed work order',
  UNKNOWN_WO: 'Work order not in the system',
  MISSING_WO: 'No work order written',
  HUMAN_REVIEW: 'Handwriting too unclear to trust',
  PART_AMBIGUOUS: 'Part name fits more than one part',
  UNKNOWN_PART: 'Part number not in the catalog',
  NAME_NUMBER_MISMATCH: "Part name doesn't match the number",
  NO_PART: 'No part written',
  UNIT_AMBIGUOUS: 'Pairs or pieces unclear',
  UNIT_REMAINDER: 'Pieces that are not whole pairs or boxes',
  UNIT_MISMATCH: 'Wrong unit written',
  UNIT_ASSUMED: 'No unit, read as pairs',
  MISSING_SIGNATURE: 'Not signed',
  MISSING_TAKEN_BY: 'No name for who took it',
  MISSING_QTY: 'No quantity',
  BAD_QTY: 'Quantity not a whole number',
  EXCEEDS_ON_HAND: 'More than the system shows on hand',
  UNUSUAL_QTY: 'Unusually large pull',
  LOCATION_MISMATCH: "Building doesn't match the W/O",
  NOT_ON_CREW: 'Person not on the W/O crew',
  DUPLICATE_PART: 'Same part listed twice',
  BAD_DATE: 'Unreadable date',
  MISSING_DATE: 'No date',
  FUTURE_DATE: 'Dated in the future',
  BEFORE_WO_OPENED: 'Dated before the W/O opened',
  BAD_LINE: 'Unreadable line',
  NO_ITEMS: 'No parts listed',
}

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

interface Props {
  log: Log | null
  canOpen: (name: string) => boolean
  onOpen: (name: string) => void
  onClear: () => void
}

export function ShiftLog({ log, canOpen, onOpen, onClear }: Props) {
  if (!log) return <p className="text-graphite-2">Loading the shift log.</p>
  const { counts, postings, pending, caught, stock } = log
  const maxCaught = Math.max(1, ...caught.map((c) => c.count))

  if (!counts.checked && !postings.length) {
    return (
      <div className="max-w-xl">
        <h2 className="font-cond text-2xl font-bold">Nothing checked this shift yet</h2>
        <p className="mt-1 text-graphite-2">
          Open a slip on the Counter tab. Every slip you check shows up here, and every slip you post lowers the
          stock below.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="max-w-2xl text-graphite-2">
          Postings go to a mocked inventory stored on this computer only. Clearing the log puts stock back where it
          started.
        </p>
        <button
          type="button"
          onClick={() => {
            if (window.confirm('Clear every check and posting from this shift? Stock goes back to the starting counts.')) onClear()
          }}
          className="cursor-pointer text-sm text-redpen underline"
        >
          Clear shift log
        </button>
      </div>

      <dl className="grid grid-cols-2 overflow-hidden rounded-md border border-rail/70 bg-steel-3 sm:grid-cols-3 lg:grid-cols-6">
        <Tally label="Slips checked" value={counts.checked} />
        <Tally label="Posted" value={counts.posted} tone="text-stamp" />
        <Tally label="On hold" value={counts.on_hold} tone={counts.on_hold ? 'text-redpen' : ''} />
        <Tally label="Waiting on a read check" value={counts.needs_review} tone={counts.needs_review ? 'text-redpen' : ''} />
        <Tally label="Ready, not posted" value={counts.ready_unposted} />
        <Tally label="Problems caught before the count" value={counts.caught} />
      </dl>

      <div className="grid gap-8 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section>
          <h2 className="font-cond text-xl font-bold">Posted</h2>
          {postings.length ? (
            <ol className="mt-3 space-y-3">
              {postings.map((p) => (
                <li key={p.id} className="rounded-md border-l-4 border-stamp bg-steel-3 px-4 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4">
                    <span className="font-semibold">
                      Entry {p.id}: {p.wo_number}, {p.location}
                    </span>
                    <span className="text-sm text-graphite-2">
                      {time(p.posted_at)}, from {titleOf(p.name)}
                    </span>
                  </div>
                  <div className="text-sm text-graphite-2">
                    Taken by {p.taken_by ?? 'unknown'}
                    {p.crew && ` (${p.crew})`}, slip dated {p.slip_date ?? 'unknown'}
                  </div>
                  <table className="mt-2 w-full text-sm">
                    <tbody>
                      {p.lines.map((l, i) => (
                        <tr key={i} className="border-t border-rail/30">
                          <td className="py-1 pr-2 font-semibold whitespace-nowrap">{l.part_number}</td>
                          <td className="py-1 pr-2">{l.name}</td>
                          <td className="py-1 pr-2 text-graphite-2">Aisle {l.aisle}</td>
                          <td className="py-1 text-right whitespace-nowrap">
                            {l.qty} {l.unit}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {p.answers.length > 0 && (
                    <p className="mt-2 text-sm text-stamp">
                      Answered at the counter before posting: {p.answers.join('; ')}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-2 text-graphite-2">No slips posted yet.</p>
          )}
        </section>

        <div className="space-y-8">
          <section>
            <h2 className="font-cond text-xl font-bold">Not posted yet</h2>
            {pending.length ? (
              <ul className="mt-3 space-y-2">
                {pending.map((p) => (
                  <li
                    key={p.name}
                    className={`flex items-start justify-between gap-3 rounded-md border-l-4 bg-steel-3 px-3 py-2.5 ${
                      p.status === 'BLOCKED' ? 'border-redpen' : 'border-amber'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="font-semibold">{titleOf(p.name)}</div>
                      <div className="text-sm text-graphite-2">
                        {p.status === 'BLOCKED'
                          ? `On hold: ${p.open_codes.map((c) => CAUGHT_LABEL[c] ?? c).join(', ').toLowerCase()}`
                          : 'Ready, waiting to be posted'}
                      </div>
                      <div className="text-xs text-graphite-2">
                        {p.wo_number ?? 'No W/O'}, {p.taken_by ?? 'unknown'}, last checked {time(p.last_seen)}
                      </div>
                    </div>
                    {canOpen(p.name) && (
                      <button
                        type="button"
                        onClick={() => onOpen(p.name)}
                        className="shrink-0 cursor-pointer rounded border border-graphite/25 bg-white px-2.5 py-1 text-sm hover:border-graphite"
                      >
                        Open
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-graphite-2">Every checked slip has been posted.</p>
            )}
          </section>

          <section>
            <h2 className="font-cond text-xl font-bold">Caught at the counter</h2>
            <p className="mt-0.5 text-sm text-graphite-2">
              First problems found on each slip. Without the check, these surface at the next physical count.
            </p>
            <ul className="mt-3 space-y-1.5">
              {caught.map((c) => (
                <li key={c.code} className="grid grid-cols-[minmax(0,1fr)_7rem_1.5rem] items-center gap-2 text-sm">
                  <span className="truncate" title={c.code}>
                    {CAUGHT_LABEL[c.code] ?? c.code}
                  </span>
                  <span className="h-2.5 rounded-sm bg-rail/30" aria-hidden>
                    <span
                      className={`block h-full rounded-sm ${c.severity === 'block' ? 'bg-redpen' : 'bg-amber'}`}
                      style={{ width: `${(c.count / maxCaught) * 100}%` }}
                    />
                  </span>
                  <span className="text-right font-semibold">{c.count}</span>
                </li>
              ))}
              {!caught.length && <li className="text-graphite-2">No problems found so far.</li>}
            </ul>
          </section>

          <section>
            <h2 className="font-cond text-xl font-bold">Stock after posting</h2>
            {stock.length ? (
              <table className="mt-2 w-full text-left text-sm">
                <thead className="text-graphite-2">
                  <tr className="border-b border-rail/60">
                    <th className="py-1.5 pr-2 font-medium">Part</th>
                    <th className="py-1.5 pr-2 text-right font-medium">Start</th>
                    <th className="py-1.5 pr-2 text-right font-medium">Posted</th>
                    <th className="py-1.5 text-right font-medium">On hand</th>
                  </tr>
                </thead>
                <tbody>
                  {stock.map((s) => (
                    <tr key={s.part_number} className="border-b border-rail/30">
                      <td className="py-1.5 pr-2">
                        <span className="font-semibold">{s.part_number}</span>{' '}
                        <span className="text-graphite-2">aisle {s.aisle}</span>
                      </td>
                      <td className="py-1.5 pr-2 text-right">{s.start}</td>
                      <td className="py-1.5 pr-2 text-right">−{s.posted}</td>
                      <td className={`py-1.5 text-right font-semibold ${s.low ? 'text-redpen' : ''}`}>
                        {s.on_hand} {s.unit}
                        {s.low && <span className="block text-xs font-medium">running low</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="mt-2 text-graphite-2">No stock has moved yet.</p>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function Tally({ label, value, tone = '' }: { label: string; value: number; tone?: string }) {
  return (
    <div className="border-r border-b border-rail/40 px-4 py-3">
      <dt className="text-sm text-graphite-2">{label}</dt>
      <dd className={`font-cond text-3xl font-bold ${tone}`}>{value}</dd>
    </div>
  )
}
