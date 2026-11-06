import { useCallback, useEffect, useRef, useState } from 'react'
import type { Evidence, Issue } from './types'

export interface Change {
  field: string
  before: string
  after: string
}

/** One discrepancy on the open document, from the first time it was found to how it was settled. */
export interface TrailEntry {
  id: string
  issue: Issue // as first found
  evidence: Evidence | null // as first found: the value read, the record, the rule
  open: boolean // still on the latest report
  resolution: { label: string; changes: Change[] } | null
}

export const issueId = (i: Issue) => `${i.code}|${i.where}`

/**
 * Keeps every discrepancy seen on one document, open or settled, so a resolved one can still be
 * inspected. `doc` resets the trail when another slip or receipt is opened.
 */
export function useTrail(doc: string | null, issues: Issue[] | undefined, evidence: Evidence[] | undefined) {
  const [entries, setEntries] = useState<TrailEntry[]>([])
  const docRef = useRef(doc)

  useEffect(() => {
    if (docRef.current !== doc) {
      docRef.current = doc
      setEntries([])
    }
  }, [doc])

  useEffect(() => {
    if (!issues) return
    const now = new Map(issues.map((i, n) => [issueId(i), { issue: i, ev: evidence?.[n] ?? null }]))
    setEntries((prev) => {
      const seen = new Set(prev.map((e) => e.id))
      const kept = prev.map((e) => ({ ...e, open: now.has(e.id) }))
      const added: TrailEntry[] = []
      for (const [id, { issue, ev }] of now) {
        if (!seen.has(id) && issue.severity !== 'info') {
          added.push({ id, issue, evidence: ev, open: true, resolution: null })
        }
      }
      return [...kept, ...added]
    })
  }, [issues, evidence])

  /** Record the clerk's answer to an issue: the fix's label and each field before and after. */
  const record = useCallback((issue: Issue, label: string, changes: Change[]) => {
    setEntries((prev) => prev.map((e) => (e.id === issueId(issue) ? { ...e, resolution: { label, changes } } : e)))
  }, [])

  return { entries, record }
}
