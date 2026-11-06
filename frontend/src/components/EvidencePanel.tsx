import type { TrailEntry } from '../evidence'
import { whereLabel } from '../slip'

/** What the document is, so the panel can show the right kind of "where it came from". */
export type DocKind =
  | { kind: 'photo'; url: string } // a handwritten slip photo: vision read, no position on the page
  | { kind: 'typed' } // typed in by the clerk: there is no image
  | { kind: 'pdf'; url: string } // a PDF page image: values carry real word boxes
  | { kind: 'image'; url: string } // a receipt image read by the vision model

interface Props {
  title: string
  entries: TrailEntry[]
  selected: string | null
  onSelect: (id: string) => void
  doc: DocKind
  postedAs?: string | null // e.g. "entry #3", once the document has posted
}

const show = (v: unknown) =>
  v === null || v === undefined || v === '' ? '(blank)' : typeof v === 'boolean' ? (v ? 'signed' : 'not signed') : String(v)

/**
 * Click a discrepancy, see the chain behind it: the document, the value read, the record it was
 * checked against, the rule that fired, and what the clerk changed.
 */
export function EvidencePanel({ title, entries, selected, onSelect, doc, postedAs }: Props) {
  const entry = entries.find((e) => e.id === selected) ?? null
  if (!entries.length) return null
  return (
    <section aria-label="Evidence" className="@container mt-5 rounded-md border border-rail/60 bg-steel-3">
      <div className="border-b border-rail/50 px-4 pt-3 pb-2">
        <h2 className="font-cond text-xl font-bold">{title}</h2>
        <p className="text-sm text-graphite-2">
          Every problem found on this document, open or settled. Pick one to see why it was raised and what was done.
        </p>
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {entries.map((e) => {
            const on = e.id === selected
            const state = e.resolution ? 'answered' : e.open ? 'open' : 'cleared'
            return (
              <li key={e.id}>
                <button
                  type="button"
                  aria-pressed={on}
                  onClick={() => onSelect(e.id)}
                  className={`cursor-pointer rounded px-2 py-1 text-left text-xs ${
                    on ? 'bg-graphite text-steel-3' : 'bg-steel-2 text-graphite hover:bg-steel'
                  }`}
                >
                  <span className="font-semibold">{whereLabel(e.issue.where)}</span>{' '}
                  <span className={on ? 'text-steel-2' : 'text-graphite-2'}>{e.issue.code}</span>{' '}
                  <span
                    className={`ml-0.5 font-semibold ${
                      on ? '' : state === 'open' ? (e.issue.severity === 'block' ? 'text-redpen' : 'text-amber') : 'text-stamp'
                    }`}
                  >
                    {state === 'open' ? (e.issue.severity === 'block' ? '● open' : '● warning') : state === 'answered' ? '✓ answered' : '✓ cleared'}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>

      {entry ? (
        <div className="grid gap-x-6 gap-y-4 p-4 @xl:grid-cols-2">
          <p className="@xl:col-span-2">
            <span className={`font-semibold ${entry.issue.severity === 'block' ? 'text-redpen' : 'text-amber'}`}>
              {whereLabel(entry.issue.where)}:
            </span>{' '}
            {entry.issue.message}
          </p>
          <Step n={1} title="Document">
            <DocumentView doc={doc} entry={entry} />
          </Step>
          <Step n={2} title="Value read">
            <Extracted entry={entry} doc={doc} />
          </Step>
          <Step n={3} title="Reference system">
            <Reference entry={entry} />
          </Step>
          <Step n={4} title="Rule">
            {entry.evidence ? (
              <>
                <p>
                  <code className="rounded-sm bg-steel-2 px-1.5 py-0.5 text-xs font-semibold">{entry.evidence.rule.code}</code>{' '}
                  {entry.evidence.rule.text}
                </p>
                <p className="mt-1 text-graphite-2">Checked against: {entry.evidence.rule.checks_against}.</p>
                <p className="mt-1 font-semibold">{entry.evidence.rule.outcome}</p>
              </>
            ) : (
              <p className="text-graphite-2">No rule details for this issue.</p>
            )}
          </Step>
          <div className="@xl:col-span-2">
            <Step n={5} title="Human correction">
              {entry.resolution ? (
                <>
                  <p>
                    The clerk answered <b>&ldquo;{entry.resolution.label}&rdquo;</b>.
                  </p>
                  {entry.resolution.changes.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {entry.resolution.changes.map((c) => (
                        <li key={c.field}>
                          {c.field}: <span className="font-hand text-base text-ballpoint line-through decoration-redpen">{c.before}</span>{' '}
                          → <span className="font-hand text-base text-stamp">{c.after}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : entry.open ? (
                <p className="text-graphite-2">
                  {entry.issue.severity === 'block' ? 'Not answered yet. This blocks posting.' : 'Not acted on. A warning does not stop posting.'}
                </p>
              ) : (
                <p className="text-graphite-2">Cleared without its own answer, after another field was corrected.</p>
              )}
              {postedAs && <p className="mt-1 font-semibold text-stamp">Posted as {postedAs}, with the answers recorded.</p>}
            </Step>
          </div>
        </div>
      ) : (
        <p className="px-4 py-3 text-sm text-graphite-2">Pick a problem above, or click a marked field on the document.</p>
      )}
    </section>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 text-sm">
      <h3 className="mb-1 flex items-center gap-2 font-cond text-base font-bold">
        <span className="inline-flex size-5 items-center justify-center rounded-full bg-graphite text-xs text-steel-3">{n}</span>
        {title}
      </h3>
      {children}
    </div>
  )
}

function DocumentView({ doc, entry }: { doc: DocKind; entry: TrailEntry }) {
  const src = entry.evidence?.extracted?.source
  const line = entry.issue.line
  if (doc.kind === 'typed') {
    return (
      <p className="text-graphite-2">
        No image: this slip was entered as data, not photographed. {line ? `Line ${line} of the slip.` : 'Slip header.'}
      </p>
    )
  }
  if (doc.kind === 'pdf' && src?.bbox && src.page_size) {
    return (
      <>
        <Crop url={doc.url} bbox={src.bbox} page={src.page_size} />
        <p className="mt-1 text-graphite-2">
          {src.document}, page {src.page ?? 1}: the word&rsquo;s real position in the PDF text layer.
        </p>
      </>
    )
  }
  return (
    <>
      <img src={doc.url} alt="The document this was read from" className="max-h-52 rounded border border-rail bg-white" />
      <p className="mt-1 text-graphite-2">
        {src?.document ?? 'This document'}
        {line ? `, line ${line}` : ', header'}. Read by a vision model, which gives no position on the page, so none is
        drawn.
      </p>
    </>
  )
}

/** Zoom into the word box on the page image, with a margin around it. */
function Crop({ url, bbox, page }: { url: string; bbox: [number, number, number, number]; page: [number, number] }) {
  const [w, h] = page
  const [x0, y0, x1, y1] = bbox
  const cx0 = Math.max(0, x0 - 60), cx1 = Math.min(w, x1 + 60)
  const cy0 = Math.max(0, y0 - 26), cy1 = Math.min(h, y1 + 26)
  const cw = cx1 - cx0, ch = cy1 - cy0
  return (
    <div
      className="relative w-full overflow-hidden rounded border border-rail bg-white"
      style={{
        aspectRatio: `${cw} / ${ch}`,
        backgroundImage: `url(${url})`,
        backgroundSize: `${(w / cw) * 100}% auto`,
        backgroundPosition: `${cw >= w ? 0 : (cx0 / (w - cw)) * 100}% ${ch >= h ? 0 : (cy0 / (h - ch)) * 100}%`,
        backgroundRepeat: 'no-repeat',
      }}
      role="img"
      aria-label="The value on the page"
    >
      <span
        className="absolute rounded-sm border-2 border-redpen bg-redpen/10"
        style={{ left: `${((x0 - cx0) / cw) * 100}%`, top: `${((y0 - cy0) / ch) * 100}%`,
                 width: `${((x1 - x0) / cw) * 100}%`, height: `${((y1 - y0) / ch) * 100}%` }}
      />
    </div>
  )
}

function Extracted({ entry, doc }: { entry: TrailEntry; doc: DocKind }) {
  const x = entry.evidence?.extracted
  if (!x) return <p className="text-graphite-2">This problem is about the document as a whole, not one field.</p>
  const src = x.source
  const low = x.confidence < 0.75
  return (
    <>
      <p>
        {x.field}
        {x.line ? ` (line ${x.line})` : ''}:{' '}
        <span className="font-hand text-lg text-ballpoint">{show(x.value)}</span>
      </p>
      {x.raw !== null && x.raw !== undefined && String(x.raw) !== String(x.value ?? '') && (
        <p className="text-graphite-2">
          Raw text: <span className="font-hand text-base">{x.raw}</span>
        </p>
      )}
      <p className={low ? 'font-semibold text-redpen' : 'text-graphite-2'}>
        Confidence {x.confidence.toFixed(2)}
        {low ? ': below 0.75, so it went to a person' : x.confidence >= 1 ? ' (exact text, or typed in)' : ': trusted (0.75 or above)'}
      </p>
      <p className="text-graphite-2">
        {src
          ? `Method: ${src.method === 'pdf_text' ? 'PDF text layer' : src.method === 'vision' ? `vision model${src.model ? ` (${src.model})` : ''}` : src.method}.`
          : doc.kind === 'typed' && x.confidence >= 1
            ? 'Method: typed in; nothing was read by a model.'
            : 'No provenance recorded: the input carries a confidence but not where the value came from.'}
      </p>
    </>
  )
}

function Reference({ entry }: { entry: TrailEntry }) {
  const r = entry.evidence?.reference
  if (!r) return <p className="text-graphite-2">Checked against the document itself; no outside record is involved.</p>
  return (
    <>
      <p className="font-semibold">{r.title}</p>
      {r.rows.length > 0 && (
        <table className="mt-1 w-full">
          <tbody>
            {r.rows.map(([k, v]) => (
              <tr key={k} className="border-b border-rail/30 align-top">
                <td className="w-[42%] py-0.5 pr-3 text-graphite-2">{k}</td>
                <td className="py-0.5">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {r.candidates.length > 0 && (
        <p className="mt-1 text-graphite-2">
          Offered as answers: <span className="text-graphite">{r.candidates.join('; ')}</span>
        </p>
      )}
    </>
  )
}
