import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { Counter } from './components/Counter'
import { DataView } from './components/DataView'
import { ImpactView } from './components/ImpactView'
import { Inbox, titleOf } from './components/Inbox'
import { ShiftLog } from './components/ShiftLog'
import { SlipPaper } from './components/SlipPaper'
import { applySet, fieldAt, pinKey, shown, whereLabel } from './slip'
import type { Fix, Issue, Meta, Report, Sample, ShiftLog as Log, Slip } from './types'

interface Loaded {
  name: string
  original: Slip
  photo: string | null
}

type View = 'counter' | 'log' | 'data' | 'impact'

export default function App() {
  const [view, setView] = useState<View>('counter')
  const [meta, setMeta] = useState<Meta | null>(null)
  const [samples, setSamples] = useState<Sample[]>([])
  const [shiftLog, setShiftLog] = useState<Log | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [slip, setSlip] = useState<Slip | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [rejected, setRejected] = useState<{ message: string; raw?: string } | null>(null)
  const [corrections, setCorrections] = useState<Record<string, string>>({})
  const [log, setLog] = useState<string[]>([])
  const [active, setActive] = useState<Issue | null>(null)
  const [postError, setPostError] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  const [showPhoto, setShowPhoto] = useState(false)
  const [busy, setBusy] = useState(false)

  const refreshLog = useCallback(() => {
    api.shiftLog().then(setShiftLog).catch(() => undefined)
  }, [])

  const open = useCallback((name: string, original: Slip, photo: string | null) => {
    setLoaded({ name, original, photo })
    setSlip(original)
    setRejected(null)
    setCorrections({})
    setLog([])
    setActive(null)
    setPostError(null)
    setShowPhoto(false)
  }, [])

  const reject = (name: string, message: string, raw?: string) => {
    setLoaded(null)
    setSlip(null)
    setReport(null)
    setSelected(name)
    setRejected({ message, raw })
  }

  const select = useCallback(
    async (name: string) => {
      setSelected(name)
      setView('counter')
      setBusy(true)
      try {
        const data = await api.sample(name)
        if (data.slip) open(name, data.slip, data.photo ?? null)
        else reject(name, data.error ?? 'This file could not be read.', data.raw)
      } catch (e) {
        reject(name, (e as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [open],
  )

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null))
    refreshLog()
    api
      .samples()
      .then((list) => {
        setSamples(list)
        if (list.length) select(list[0].name)
      })
      .catch((e: Error) => setRejected({ message: `Could not reach the slip checker API. Is it running? (${e.message})` }))
  }, [select, refreshLog])

  // Re-check the slip every time it changes: on load and after each answer. Each check
  // is recorded in the shift log under the slip's name.
  const name = loaded?.name ?? null
  useEffect(() => {
    if (!slip) return
    const ctrl = new AbortController()
    api
      .validate(slip, name, ctrl.signal)
      .then((r) => {
        setReport(r)
        setRejected(null)
        refreshLog()
      })
      .catch((e: Error) => {
        if (e.name !== 'AbortError') {
          setReport(null)
          setRejected({ message: e.message })
        }
      })
    return () => ctrl.abort()
  }, [slip, name, refreshLog])

  const upload = async (file: File) => {
    setBusy(true)
    setSelected(null)
    setView('counter')
    try {
      if (file.name.toLowerCase().endsWith('.json')) {
        const text = await file.text()
        try {
          open(file.name, JSON.parse(text), null)
        } catch (e) {
          reject(file.name, `${file.name} is not valid JSON (${(e as Error).message}).`, text)
        }
      } else {
        const { slip: read } = await api.extract(file, live)
        open(file.name, read, URL.createObjectURL(file))
      }
    } catch (e) {
      reject(file.name, (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // Answers can arrive faster than re-validation, so every update builds on the latest
  // slip (functional updates), never on the one this render happened to see.
  const answer = (issue: Issue, set: Record<string, unknown>, label: string) => {
    const before = slip
    if (!before) return
    setCorrections((prev) => {
      const next = { ...prev }
      for (const key of Object.keys(set)) {
        const k = pinKey(issue.line, key)
        if (!(k in next)) next[k] = shown(fieldAt(before, issue.line, key))
      }
      return next
    })
    setSlip((prev) => (prev ? applySet(prev, issue.line, set) : prev))
    setLog((prev) => [...prev, `${whereLabel(issue.where)}: ${label}`])
    setActive(null)
  }

  const onFix = (issue: Issue, fix: Fix) => answer(issue, fix.set, fix.label)
  const onEnter = (issue: Issue, value: string) => issue.key && answer(issue, { [issue.key]: value }, value)

  const onPost = async () => {
    if (!slip || !loaded) return
    setPostError(null)
    try {
      const posting = await api.post(slip, loaded.name, log)
      setReport((r) => (r ? { ...r, posted: posting } : r))
      refreshLog()
    } catch (e) {
      setPostError((e as Error).message)
    }
  }

  const clearShift = async () => {
    setShiftLog(await api.clearShiftLog())
    if (slip) setSlip({ ...slip }) // re-check the open slip against restored stock
  }

  const reset = () => loaded && open(loaded.name, loaded.original, loaded.photo)
  const provenance = (loaded?.original._provenance ?? null) as { kind?: string; model?: string } | null
  const posting = report?.posted ?? null
  const counts = shiftLog?.counts

  return (
    <div className="mx-auto max-w-[96rem] px-4 pb-16 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4 pt-5 pb-4">
        <div>
          <h1 className="font-cond text-3xl font-bold tracking-tight">Slip check</h1>
          <p className="mt-0.5 max-w-xl text-graphite-2">
            Find the problems on a checkout slip at the counter, while the crew is still reachable, not days later at
            the count.
          </p>
        </div>
        <div className="text-right text-sm text-graphite-2">
          <label className={`inline-flex items-center gap-2 ${meta?.live_available ? 'cursor-pointer' : 'opacity-60'}`}>
            <input
              type="checkbox"
              checked={live}
              disabled={!meta?.live_available}
              onChange={(e) => setLive(e.target.checked)}
              className="size-4 accent-ballpoint"
            />
            Read uploaded photos with {meta?.model ?? 'the vision model'}
          </label>
          <div className="mt-0.5">
            {meta?.live_available
              ? live
                ? 'Live: each photo is one API call.'
                : 'Mock: photos use cached readings.'
              : 'Mock: photos use cached readings. Set ANTHROPIC_API_KEY for live.'}
          </div>
        </div>
      </header>

      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 border-b border-rail/60">
        <div role="tablist" aria-label="View" className="flex gap-1">
          {(
            [
              ['counter', 'Counter'],
              ['log', 'Shift log'],
              ['data', 'Data'],
              ['impact', 'Impact (estimated)'],
            ] as const
          ).map(([v, label]) => (
            <button
              key={v}
              role="tab"
              type="button"
              aria-selected={view === v}
              onClick={() => {
                setView(v)
                if (v === 'log') refreshLog()
              }}
              className={`-mb-px cursor-pointer border-b-[3px] px-3 pt-1 pb-2 font-cond text-lg font-semibold ${
                view === v ? 'border-graphite text-graphite' : 'border-transparent text-graphite-2 hover:text-graphite'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {counts && (
          <button
            type="button"
            onClick={() => {
              setView('log')
              refreshLog()
            }}
            className="mb-2 flex cursor-pointer flex-wrap gap-x-5 gap-y-1 text-sm text-graphite-2 hover:text-graphite"
            aria-label="Open the shift log"
          >
            <span>
              <b className="font-semibold text-stamp">{counts.posted}</b> posted
            </span>
            <span>
              <b className={`font-semibold ${counts.on_hold ? 'text-redpen' : 'text-graphite'}`}>{counts.on_hold}</b> on hold
            </span>
            <span>
              <b className={`font-semibold ${counts.needs_review ? 'text-redpen' : 'text-graphite'}`}>
                {counts.needs_review}
              </b>{' '}
              waiting on a read check
            </span>
            <span>
              <b className="font-semibold text-graphite">{counts.caught}</b> problems caught
            </span>
          </button>
        )}
      </div>

      {view === 'impact' ? (
        <div className="mt-6">
          <ImpactView />
        </div>
      ) : view === 'data' ? (
        <div className="mt-6">
          <DataView />
        </div>
      ) : view === 'log' ? (
        <div className="mt-6">
          <ShiftLog
            log={shiftLog}
            canOpen={(n) => samples.some((s) => s.name === n)}
            onOpen={select}
            onClear={clearShift}
          />
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_26rem]">
          <aside className="lg:sticky lg:top-6 lg:self-start">
            <Inbox samples={samples} selected={selected} onSelect={select} onUpload={upload} />
          </aside>

          <main className={`min-w-0 ${busy ? 'opacity-60' : ''}`} aria-busy={busy}>
            {rejected ? (
              <Rejected name={selected ?? loaded?.name ?? null} {...rejected} />
            ) : slip ? (
              <>
                <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
                  <p className="text-graphite-2">
                    <span className="font-semibold text-graphite">{titleOf(loaded?.name ?? '')}</span>
                    {provenance?.kind && <span>, read from a photo ({provenance.kind})</span>}
                  </p>
                  <div className="flex gap-4 text-sm">
                    {loaded?.photo && (
                      <button type="button" className="cursor-pointer underline" onClick={() => setShowPhoto((v) => !v)}>
                        {showPhoto ? 'Hide photo' : 'Show photo'}
                      </button>
                    )}
                    {log.length > 0 && !posting && (
                      <button type="button" className="cursor-pointer underline" onClick={reset}>
                        Undo answers
                      </button>
                    )}
                  </div>
                </div>
                {showPhoto && loaded?.photo && (
                  <img src={loaded.photo} alt="Photo of the paper slip" className="mb-4 max-h-[28rem] rounded border border-rail" />
                )}
                <SlipPaper
                  slip={slip}
                  report={report}
                  corrections={corrections}
                  active={active}
                  onPick={setActive}
                  posted={!!posting}
                />
                <details className="mt-4 text-sm text-graphite-2">
                  <summary className="cursor-pointer">What the checker received</summary>
                  <pre className="mt-2 max-h-80 overflow-auto rounded bg-steel-3 p-3 text-xs text-graphite">
                    {JSON.stringify(slip, null, 2)}
                  </pre>
                </details>
              </>
            ) : (
              <p className="text-graphite-2">Pick a slip on the left, or drop in your own.</p>
            )}
          </main>

          <section aria-label="At the counter" className="lg:col-start-2 xl:col-start-auto">
            {report && slip && !rejected && (
              <Counter
                report={report}
                active={active}
                onPick={setActive}
                onFix={onFix}
                onEnter={onEnter}
                log={log}
                posting={posting}
                postError={postError}
                onPost={onPost}
                onShowLog={() => {
                  setView('log')
                  refreshLog()
                }}
              />
            )}
          </section>
        </div>
      )}
    </div>
  )
}

function Rejected({ name, message, raw }: { name: string | null; message: string; raw?: string }) {
  return (
    <div className="rounded-md border-l-4 border-redpen bg-steel-3 p-5">
      <h2 className="font-cond text-xl font-bold">{name ? `${titleOf(name)} was not checked` : 'Nothing was checked'}</h2>
      <p className="mt-1">{message}</p>
      <p className="mt-1 text-sm text-graphite-2">
        Nothing was posted. Re-enter the slip from the paper copy, or upload a clearer photo.
      </p>
      {raw && (
        <pre className="mt-3 max-h-60 overflow-auto rounded bg-white p-3 text-xs whitespace-pre-wrap">{raw}</pre>
      )}
    </div>
  )
}
