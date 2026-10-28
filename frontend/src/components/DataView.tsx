import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { DataView as Data, StockChange } from '../types'

type Table = 'parts' | 'work_orders'
type PartFilter = 'all' | 'changed' | 'low'
type WoFilter = 'all' | 'OPEN' | 'CLOSED' | 'issued'

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
const POLL_MS = 4000

/** The reference data the checker uses, live: on-hand drops as slips are posted. */
export function DataView() {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [updated, setUpdated] = useState<Date | null>(null)
  const [table, setTable] = useState<Table>('parts')
  const [query, setQuery] = useState('')
  const [partFilter, setPartFilter] = useState<PartFilter>('all')
  const [woFilter, setWoFilter] = useState<WoFilter>('all')

  // Poll while the tab is open, so a posting from another window shows up too.
  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .data()
        .then((d) => {
          if (!alive) return
          setData(d)
          setUpdated(new Date())
          setError(null)
        })
        .catch((e: Error) => alive && setError(e.message))
    load()
    const id = window.setInterval(load, POLL_MS)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [])

  const q = query.trim().toLowerCase()
  const parts = useMemo(
    () =>
      (data?.parts ?? []).filter(
        (p) =>
          (partFilter === 'all' || (partFilter === 'changed' ? p.posted > 0 : p.low)) &&
          (!q || `${p.part_number} ${p.name} ${p.aisle}`.toLowerCase().includes(q)),
      ),
    [data, partFilter, q],
  )
  const workOrders = useMemo(
    () =>
      (data?.work_orders ?? []).filter(
        (w) =>
          (woFilter === 'all' || (woFilter === 'issued' ? w.postings > 0 : w.status === woFilter)) &&
          (!q || `${w.wo_number} ${w.crew} ${w.location} ${w.members.join(' ')}`.toLowerCase().includes(q)),
      ),
    [data, woFilter, q],
  )
  const groups = useMemo(() => groupByPosting(data?.changes ?? []), [data])

  if (error && !data) return <p className="text-redpen">Could not load the data: {error}</p>
  if (!data) return <p className="text-graphite-2">Loading the data.</p>

  const latest = data.latest_posting_id
  const changedCount = data.parts.filter((p) => p.posted > 0).length
  const lowCount = data.parts.filter((p) => p.low).length
  const issuedCount = data.work_orders.filter((w) => w.postings > 0).length

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="max-w-2xl text-graphite-2">
          The catalog and work orders the checker reads, as the mocked inventory holds them now. Posting a slip
          lowers on-hand here straight away; the newest changes are highlighted.
        </p>
        <p className="text-sm text-graphite-2" aria-live="polite">
          {updated && `Updated ${updated.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}`}
          {error && <span className="text-redpen"> (last refresh failed)</span>}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="Table" className="inline-flex rounded-md border border-rail bg-steel-3 p-0.5">
          {(
            [
              ['parts', `Parts and stock (${data.parts.length})`],
              ['work_orders', `Work orders (${data.work_orders.length})`],
            ] as const
          ).map(([t, label]) => (
            <button
              key={t}
              role="tab"
              type="button"
              aria-selected={table === t}
              onClick={() => setTable(t)}
              className={`cursor-pointer rounded px-3 py-1.5 text-sm font-semibold ${
                table === t ? 'bg-graphite text-steel-3' : 'text-graphite-2 hover:text-graphite'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {table === 'parts' ? (
          <Filter
            value={partFilter}
            onChange={setPartFilter}
            options={[
              ['all', 'All'],
              ['changed', `Moved this shift (${changedCount})`],
              ['low', `Running low (${lowCount})`],
            ]}
          />
        ) : (
          <Filter
            value={woFilter}
            onChange={setWoFilter}
            options={[
              ['all', 'All'],
              ['OPEN', 'Open'],
              ['CLOSED', 'Closed'],
              ['issued', `Issued this shift (${issuedCount})`],
            ]}
          />
        )}

        <label className="ml-auto block w-full sm:w-64">
          <span className="sr-only">Search</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={table === 'parts' ? 'Search part, name or aisle' : 'Search W/O, crew, person or building'}
            className="w-full rounded-md border border-rail bg-steel-3 px-3 py-1.5 text-sm"
          />
        </label>
      </div>

      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 overflow-x-auto rounded-md border border-rail/70 bg-steel-3">
          {table === 'parts' ? (
            <table className="w-full text-left text-sm sm:min-w-[40rem]">
              <thead className="text-graphite-2">
                <tr className="border-b border-rail/60">
                  <th className="px-3 py-2 font-medium">Part</th>
                  <th className="hidden px-3 py-2 font-medium sm:table-cell">Aisle</th>
                  <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Start</th>
                  <th className="px-3 py-2 text-right font-medium">Posted</th>
                  <th className="px-3 py-2 text-right font-medium">On hand</th>
                </tr>
              </thead>
              <tbody>
                {parts.map((p) => {
                  const fresh = latest !== null && p.last?.posting_id === latest
                  return (
                    <tr
                      // Re-keying on the latest posting replays the highlight when it changes.
                      key={`${p.part_number}-${fresh ? latest : 0}`}
                      className={`border-b border-rail/30 ${fresh ? 'row-fresh' : ''}`}
                    >
                      <td className="px-3 py-2">
                        <span className="font-semibold">{p.part_number}</span>{' '}
                        <span className="block text-graphite-2 sm:inline">
                          {p.name}
                          <span className="sm:hidden">, aisle {p.aisle}, started at {p.start}</span>
                        </span>
                      </td>
                      <td className="hidden px-3 py-2 sm:table-cell">{p.aisle}</td>
                      <td className="hidden px-3 py-2 text-right text-graphite-2 sm:table-cell">{p.start}</td>
                      <td className="px-3 py-2 text-right">
                        {p.posted > 0 ? (
                          <span title={p.last ? `Last: entry ${p.last.posting_id} at ${time(p.last.posted_at)}` : undefined}>
                            −{p.posted}
                          </span>
                        ) : (
                          <span className="text-graphite-2">0</span>
                        )}
                      </td>
                      <td className={`px-3 py-2 text-right font-semibold whitespace-nowrap ${p.low ? 'text-redpen' : ''}`}>
                        {p.on_hand} {p.unit}
                        {p.low && <span className="block text-xs font-medium">low, usual pull {p.max_per_pull}</span>}
                      </td>
                    </tr>
                  )
                })}
                {!parts.length && <Empty cols={5} />}
              </tbody>
            </table>
          ) : (
            <table className="w-full text-left text-sm sm:min-w-[44rem]">
              <thead className="text-graphite-2">
                <tr className="border-b border-rail/60">
                  <th className="px-3 py-2 font-medium">W/O</th>
                  <th className="px-3 py-2 font-medium">Crew</th>
                  <th className="hidden px-3 py-2 font-medium sm:table-cell">Location</th>
                  <th className="hidden px-3 py-2 font-medium md:table-cell">Dates</th>
                  <th className="px-3 py-2 text-right font-medium">Issued this shift</th>
                </tr>
              </thead>
              <tbody>
                {workOrders.map((w) => {
                  const fresh = latest !== null && w.last?.posting_id === latest
                  return (
                    <tr key={`${w.wo_number}-${fresh ? latest : 0}`} className={`border-b border-rail/30 ${fresh ? 'row-fresh' : ''}`}>
                      <td className="px-3 py-2">
                        <span className="font-semibold">{w.wo_number}</span>{' '}
                        <span
                          className={`ml-1 rounded px-1.5 py-0.5 text-xs font-semibold ${
                            w.status === 'OPEN' ? 'bg-stamp/15 text-stamp' : 'bg-rail/30 text-graphite-2'
                          }`}
                        >
                          {w.status === 'OPEN' ? 'Open' : 'Closed'}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        {w.crew}
                        <span className="block text-xs text-graphite-2">{w.members.join(', ')}</span>
                        <span className="block text-xs text-graphite-2 sm:hidden">{w.location}</span>
                      </td>
                      <td className="hidden px-3 py-2 sm:table-cell">{w.location}</td>
                      <td className="hidden px-3 py-2 whitespace-nowrap text-graphite-2 md:table-cell">
                        Opened {w.opened}
                        {w.closed && <span className="block">Closed {w.closed}</span>}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {w.postings ? (
                          <>
                            {w.postings} {w.postings === 1 ? 'slip' : 'slips'}, {w.lines} {w.lines === 1 ? 'line' : 'lines'}
                            {w.last && <span className="block text-xs text-graphite-2">last at {time(w.last.posted_at)}</span>}
                          </>
                        ) : (
                          <span className="text-graphite-2">none</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
                {!workOrders.length && <Empty cols={5} />}
              </tbody>
            </table>
          )}
        </div>

        <section aria-label="Stock changes">
          <h2 className="font-cond text-xl font-bold">Stock changes</h2>
          {groups.length ? (
            <ol className="mt-3 space-y-3">
              {groups.map((g) => (
                <li
                  key={g.posting_id}
                  className={`rounded-md border-l-4 bg-steel-3 px-3 py-2.5 ${
                    g.posting_id === latest ? 'border-stamp' : 'border-rail'
                  }`}
                >
                  <div className="text-sm font-semibold">
                    Entry {g.posting_id}, {time(g.posted_at)}
                  </div>
                  <div className="text-xs text-graphite-2">
                    {g.wo_number}, taken by {g.taken_by ?? 'unknown'}
                  </div>
                  <ul className="mt-1.5 space-y-1 text-sm">
                    {g.lines.map((c) => (
                      <li key={c.part_number} className="flex justify-between gap-3">
                        <span className="min-w-0 truncate">
                          <span className="font-semibold">{c.part_number}</span>{' '}
                          <span className="text-graphite-2">{c.name}</span>
                        </span>
                        <span className="shrink-0 whitespace-nowrap">
                          {c.before} → <b className="font-semibold">{c.after}</b> {c.unit}
                        </span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-2 text-graphite-2">
              No stock has moved yet. Post a slip on the Counter tab and the change appears here.
            </p>
          )}
        </section>
      </div>
    </div>
  )
}

function groupByPosting(changes: StockChange[]) {
  const groups: (Pick<StockChange, 'posting_id' | 'posted_at' | 'wo_number' | 'taken_by'> & { lines: StockChange[] })[] = []
  for (const c of changes) {
    const last = groups[groups.length - 1]
    if (last && last.posting_id === c.posting_id) last.lines.push(c)
    else groups.push({ posting_id: c.posting_id, posted_at: c.posted_at, wo_number: c.wo_number, taken_by: c.taken_by, lines: [c] })
  }
  return groups
}

function Filter<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T
  onChange: (v: T) => void
  options: readonly (readonly [T, string])[]
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter">
      {options.map(([v, label]) => (
        <button
          key={v}
          type="button"
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className={`cursor-pointer rounded-full border px-3 py-1 text-sm ${
            value === v ? 'border-graphite bg-graphite text-steel-3' : 'border-rail bg-steel-3 hover:border-graphite-2'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function Empty({ cols }: { cols: number }) {
  return (
    <tr>
      <td colSpan={cols} className="px-3 py-4 text-graphite-2">
        Nothing matches. Clear the search or pick another filter.
      </td>
    </tr>
  )
}
