// A tiny hook that runs an async function and tracks its three outcomes.
//
// It exists to prevent the bug that stalled the login page: every path here
// ends by setting loading to false, so a screen can never be left spinning
// forever. Pages get { data, error, loading, reload } and stay readable.

import { useCallback, useEffect, useState } from 'react'

export function useAsync(asyncFunction, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  // useCallback keeps the same function identity between renders unless deps
  // change, so the effect below does not re-run on every render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(asyncFunction, deps)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await run())
    } catch (err) {
      setError(err.message || 'Something went wrong.')
      setData(null)
    } finally {
      // Always - success or failure. This is the important line.
      setLoading(false)
    }
  }, [run])

  useEffect(() => {
    load()
  }, [load])

  return { data, error, loading, reload: load }
}
