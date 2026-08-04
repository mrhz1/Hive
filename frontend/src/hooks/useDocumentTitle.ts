import { useEffect } from 'react'

const SUFFIX = 'Hive Admin'

/** Sets document.title per page and restores it on unmount. */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    const previous = document.title
    document.title = title ? `${title} · ${SUFFIX}` : SUFFIX
    return () => {
      document.title = previous
    }
  }, [title])
}
