import type { Issue, Slip } from './types'

/** A slip field is either a plain value (typed) or {value, confidence, raw} (read from a photo). */
export interface FieldView {
  value: unknown
  confidence: number
  raw: string | null
}

export function readField(x: unknown): FieldView {
  if (x && typeof x === 'object' && !Array.isArray(x) && 'value' in x) {
    const f = x as { value: unknown; confidence?: number; raw?: string | null }
    return { value: f.value, confidence: f.confidence ?? 1, raw: f.raw ?? null }
  }
  return { value: x ?? null, confidence: 1, raw: null }
}

/** What is physically on the paper: the characters as read when we have them, not the
 *  reader's cleaned-up value, so "can't read" sits next to the scrawl that caused it. */
export function shown(f: FieldView): string {
  const v = f.raw ?? f.value
  if (v === null || v === undefined || v === '') return ''
  return String(v)
}

export function items(slip: Slip): unknown[] {
  return Array.isArray(slip.items) ? slip.items : []
}

export function fieldAt(slip: Slip, line: number | null, key: string): FieldView {
  if (line === null) return readField(slip[key])
  const item = items(slip)[line - 1]
  return readField(item && typeof item === 'object' ? (item as Slip)[key] : undefined)
}

/** Apply answered values to the header (line null) or to items[line - 1]. Values set by the
 *  clerk are plain, so the validator treats them as confirmed (confidence 1.0). */
export function applySet(slip: Slip, line: number | null, set: Record<string, unknown>): Slip {
  const next = structuredClone(slip)
  if (line === null) return Object.assign(next, set)
  const row = items(next)[line - 1]
  if (row && typeof row === 'object') Object.assign(row, set)
  return next
}

/** Issues are rebuilt on every validation, so compare by identity of meaning, not object. */
export const sameIssue = (a: Issue | null, b: Issue | null) =>
  !!a && !!b && a.code === b.code && a.where === b.where

export const pinKey =(line: number | null, key: string) => `${line ?? 'h'}:${key}`

export function issuesAt(issues: Issue[], line: number | null, key: string): Issue[] {
  return issues.filter((i) => i.line === line && i.key === key)
}

const FIELD_LABEL: Record<string, string> = {
  wo_number: 'W/O number',
  taken_by: 'Taken by',
  part_number: 'part number',
  part_name: 'description',
}

/** "line 1 part_number" -> "Line 1, part number"; "wo_number" -> "W/O number". */
export function whereLabel(where: string): string {
  const m = where.match(/^line (\d+)\s*(\w+)?$/)
  if (m) return m[2] ? `Line ${m[1]}, ${FIELD_LABEL[m[2]] ?? m[2]}` : `Line ${m[1]}`
  const label = FIELD_LABEL[where] ?? where.replace(/_/g, ' ')
  return label.charAt(0).toUpperCase() + label.slice(1)
}

/** Short margin notes, written on the slip in red pen next to the field they are about. */
export const MARGIN_NOTE: Record<string, string> = {
  CLOSED_WO: 'closed W/O',
  UNKNOWN_WO: 'no such W/O',
  MISSING_WO: 'W/O?',
  HUMAN_REVIEW: "can't read",
  PART_AMBIGUOUS: 'which one?',
  UNKNOWN_PART: 'not in catalog',
  NAME_NUMBER_MISMATCH: "name doesn't match #",
  NO_PART: 'what part?',
  UNIT_AMBIGUOUS: 'pairs or pieces?',
  UNIT_REMAINDER: 'half a pair?',
  UNIT_MISMATCH: 'unit?',
  UNIT_ASSUMED: 'read as pairs',
  UNIT_CONVERTED: 'converted',
  MISSING_SIGNATURE: 'not signed',
  MISSING_TAKEN_BY: 'who?',
  MISSING_QTY: 'how many?',
  BAD_QTY: 'how many?',
  EXCEEDS_ON_HAND: 'more than on hand',
  UNUSUAL_QTY: 'a lot',
  LOCATION_MISMATCH: 'wrong building?',
  NOT_ON_CREW: 'not on this crew',
  DUPLICATE_PART: 'listed twice',
  BAD_DATE: 'date?',
  MISSING_DATE: 'no date',
  FUTURE_DATE: 'future date',
  BEFORE_WO_OPENED: 'before W/O opened',
  NAME_MATCHED: 'matched',
  LOCATION_FROM_WO: 'from W/O',
}
