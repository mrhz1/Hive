import { useEffect, useState } from 'react'

/**
 * The value, once it has stopped changing for `delay` ms.
 *
 * Used to keep a search box off the wire on every keystroke: each query
 * here is a Hive scan, and typing 'siemens' should be one of them rather
 * than seven.
 */
export function useDebounced<T>(value: T, delay = 300): T {
  const [settled, setSettled] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])

  return settled
}
