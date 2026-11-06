import type { ShiftLog } from '../types'

export type View = 'counter' | 'receiving' | 'log' | 'data' | 'adversarial' | 'impact'

const GROUPS: { title: string; items: { view: View; label: string; hint: string }[] }[] = [
  {
    title: 'At the counter',
    items: [
      { view: 'counter', label: 'Counter', hint: 'Check a checkout slip' },
      { view: 'receiving', label: 'Receiving', hint: 'Check a delivery against its PO' },
    ],
  },
  {
    title: 'Records',
    items: [
      { view: 'log', label: 'Shift log', hint: 'What posted, what is on hold' },
      { view: 'data', label: 'Data', hint: 'Parts, work orders, stock' },
    ],
  },
  {
    title: 'Does it hold up?',
    items: [
      { view: 'adversarial', label: 'Adversarial suite', hint: 'Cases built to break it' },
      { view: 'impact', label: 'Impact (estimated)', hint: 'Time and cost, modeled' },
    ],
  },
]

/** Left rail on wide screens; a sideways-scrolling row on phones. */
export function SideNav({
  view,
  onView,
  counts,
}: {
  view: View
  onView: (v: View) => void
  counts: ShiftLog['counts'] | undefined
}) {
  return (
    <nav aria-label="Sections" className="lg:sticky lg:top-6 lg:self-start">
      <div className="-mx-4 flex gap-1 overflow-x-auto border-b border-rail/60 px-4 lg:mx-0 lg:block lg:overflow-visible lg:border-0 lg:px-0">
        {GROUPS.map((g, gi) => (
          <div
            key={g.title}
            className={`flex shrink-0 gap-1 lg:block ${
              gi ? 'border-l border-rail/60 pl-1 lg:mt-6 lg:border-0 lg:pl-0' : ''
            }`}
          >
            <h2 className="hidden px-3 pb-1.5 text-xs font-semibold tracking-widest text-rail uppercase lg:block">
              {g.title}
            </h2>
            {g.items.map((it) => {
              const on = view === it.view
              return (
                <button
                  key={it.view}
                  type="button"
                  aria-current={on ? 'page' : undefined}
                  onClick={() => onView(it.view)}
                  className={`-mb-px block shrink-0 cursor-pointer border-b-[3px] px-3 pt-1 pb-2 text-left whitespace-nowrap lg:mb-0.5 lg:w-full lg:rounded-r lg:border-b-0 lg:border-l-[3px] lg:py-1.5 ${
                    on
                      ? 'border-graphite text-graphite lg:bg-steel-2'
                      : 'border-transparent text-graphite-2 hover:text-graphite lg:hover:bg-steel-2/60'
                  }`}
                >
                  <span className="font-cond text-lg leading-tight font-semibold">{it.label}</span>
                  <span className="hidden text-sm leading-snug text-graphite-2 lg:block">{it.hint}</span>
                </button>
              )
            })}
            {g.title === 'Records' && counts && (
              <button
                type="button"
                onClick={() => onView('log')}
                aria-label="Open the shift log"
                className="mx-3 mt-2 hidden cursor-pointer rounded border border-rail/50 px-3 py-2 text-left text-sm text-graphite-2 hover:border-rail lg:block"
              >
                <span className="mb-1 block text-xs font-semibold tracking-widest text-rail uppercase">This shift</span>
                <Count n={counts.posted} label="posted" tone="text-stamp" />
                <Count n={counts.on_hold} label="on hold" tone={counts.on_hold ? 'text-redpen' : 'text-graphite'} />
                <Count
                  n={counts.needs_review}
                  label="waiting on a read check"
                  tone={counts.needs_review ? 'text-redpen' : 'text-graphite'}
                />
                <Count n={counts.caught} label="problems caught" tone="text-graphite" />
              </button>
            )}
          </div>
        ))}
      </div>
    </nav>
  )
}

function Count({ n, label, tone }: { n: number; label: string; tone: string }) {
  return (
    <span className="block">
      <b className={`inline-block min-w-6 font-semibold ${tone}`}>{n}</b> {label}
    </span>
  )
}
