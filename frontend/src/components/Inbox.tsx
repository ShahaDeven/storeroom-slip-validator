import { useState } from 'react'
import type { Sample } from '../types'

const TITLES: Record<string, string> = {
  '01_clean.json': 'Clean slip',
  '02_closed_wo.json': 'Closed work order',
  '03_pairs_no_unit.json': 'Hinges, no unit',
  '04_pieces_converted.json': 'Gloves counted in pieces',
  '05_name_only_clear.json': 'Name only, one match',
  '06_name_only_ambiguous.json': 'Name only, two matches',
  '07_unsigned_big_pull.json': 'Unsigned, large pull',
  '08_wo_typo.json': 'Mistyped W/O number',
  '09_exceeds_on_hand.json': 'More than the shelf holds',
  '10_hard_case.json': 'Hard case: four problems',
  '11_invalid_input.json': 'Mostly blank slip',
  '12_truncated.json': 'Corrupted file',
  '13_custodial_restock.json': 'Custodial restock',
  '14_ear_plugs_in_pieces.json': 'Ear plugs counted in pieces',
  '15_not_on_crew.json': 'Taken on another crew’s W/O',
  '16_wrong_building.json': 'Wrong building',
  '17_name_contradicts_number.json': 'Name contradicts number',
  '18_same_part_twice.json': 'Same part twice',
  '19_dated_before_wo.json': 'Dated before the W/O',
  '20_weekly_plumbing_pull.json': 'Weekly plumbing pull',
}

export const titleOf = (name: string) =>
  TITLES[name] ?? name.replace(/^\d+_/, '').replace(/\.\w+$/, '').replace(/_/g, ' ')

interface Props {
  samples: Sample[]
  selected: string | null
  onSelect: (name: string) => void
  onUpload: (file: File) => void
}

export function Inbox({ samples, selected, onSelect, onUpload }: Props) {
  const [dragging, setDragging] = useState(false)
  const typed = samples.filter((s) => s.kind === 'slip')
  const photos = samples.filter((s) => s.kind === 'photo')

  const item = (s: Sample) => (
    <li key={s.name}>
      <button
        type="button"
        onClick={() => onSelect(s.name)}
        aria-current={selected === s.name}
        className={`w-full cursor-pointer rounded px-2.5 py-1.5 text-left text-[0.95rem] ${
          selected === s.name ? 'bg-graphite text-steel-3' : 'hover:bg-steel-3'
        }`}
      >
        {titleOf(s.name)}
      </button>
    </li>
  )

  return (
    <nav aria-label="Slips" className="space-y-5">
      {/* Small screens: one dropdown instead of a long list above the slip. */}
      <label className="block lg:hidden">
        <span className="font-cond text-sm font-semibold text-graphite-2">Slip</span>
        <select
          value={selected ?? ''}
          onChange={(e) => onSelect(e.target.value)}
          className="mt-1 block w-full rounded-md border border-rail bg-steel-3 px-3 py-2"
        >
          {selected === null && <option value="">Your upload</option>}
          <optgroup label="Typed in by the clerk">
            {typed.map((s) => (
              <option key={s.name} value={s.name}>{titleOf(s.name)}</option>
            ))}
          </optgroup>
          {photos.length > 0 && (
            <optgroup label="Photographed">
              {photos.map((s) => (
                <option key={s.name} value={s.name}>{titleOf(s.name)}</option>
              ))}
            </optgroup>
          )}
        </select>
      </label>
      <div className="hidden lg:block">
        <h2 className="px-2.5 font-cond text-sm font-semibold text-graphite-2">Typed in by the clerk</h2>
        <ul className="mt-1 space-y-0.5">{typed.map(item)}</ul>
      </div>
      <div className="hidden lg:block">
        <h2 className="px-2.5 font-cond text-sm font-semibold text-graphite-2">Photographed</h2>
        {photos.length ? (
          <ul className="mt-1 space-y-0.5">{photos.map(item)}</ul>
        ) : (
          <p className="mt-1 px-2.5 text-sm text-graphite-2">
            No photos yet. Add them to data/photos/ as described in WHAT_TO_WRITE.md.
          </p>
        )}
      </div>
      <label
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const file = e.dataTransfer.files[0]
          if (file) onUpload(file)
        }}
        className={`block cursor-pointer rounded-md border-2 border-dashed px-3 py-3 text-center text-sm lg:py-4 ${
          dragging ? 'border-ballpoint bg-steel-3' : 'border-rail hover:border-graphite-2'
        }`}
      >
        <span className="font-semibold">Check your own slip</span>
        <span className="mt-0.5 block text-graphite-2">Drop a photo or a .json file, or click to choose</span>
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif,.json,application/json"
          className="sr-only"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) onUpload(file)
            e.target.value = ''
          }}
        />
      </label>
    </nav>
  )
}
