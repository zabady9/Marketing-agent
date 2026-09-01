import { useCallback, useEffect, useState } from 'react'
import type { AdminListParams, PagedResult } from '../adminTypes'

type LoadState = 'loading' | 'loaded' | 'error'

const PAGE_SIZE = 20

// Encapsulates the page/pageSize/includeDeleted/filter state shared by every
// admin list page, plus the fetch effect — follows ProjectsListPage's
// cancellation-flag pattern (no react-query/SWR anywhere in this codebase).
export function useAdminList<T>(
  fetchPage: (params: AdminListParams) => Promise<PagedResult<T>>,
  filters: Record<string, string | undefined> = {},
) {
  const [page, setPage] = useState(0)
  const [pageSize] = useState(PAGE_SIZE)
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [items, setItems] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [state, setState] = useState<LoadState>('loading')
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  const filterKey = JSON.stringify(filters)

  useEffect(() => {
    let cancelled = false
    setState('loading')
    setError(null)
    fetchPage({
      limit: pageSize,
      offset: page * pageSize,
      include_deleted: includeDeleted,
      ...filters,
    })
      .then((result) => {
        if (cancelled) return
        setItems(result.items)
        setTotal(result.total)
        setState('loaded')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load.')
        setState('error')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, includeDeleted, filterKey, reloadToken])

  const refetch = useCallback(() => setReloadToken((t) => t + 1), [])

  // Reset to page 0 whenever filters or includeDeleted change, so the user
  // isn't left staring at an out-of-range empty page.
  const setIncludeDeletedAndReset = useCallback((value: boolean) => {
    setIncludeDeleted(value)
    setPage(0)
  }, [])

  return {
    items,
    setItems,
    total,
    state,
    error,
    page,
    pageSize,
    totalPages: Math.max(1, Math.ceil(total / pageSize)),
    setPage,
    includeDeleted,
    setIncludeDeleted: setIncludeDeletedAndReset,
    refetch,
  }
}
