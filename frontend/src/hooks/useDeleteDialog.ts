import { useCallback, useState } from 'react'

export function useDeleteDialog<T>(onConfirmed: (target: T) => Promise<unknown>) {
  const [target, setTarget] = useState<T | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const request = useCallback((row: T) => setTarget(row), [])

  const cancel = useCallback(() => {
    if (!isDeleting) setTarget(null)
  }, [isDeleting])

  const confirm = useCallback(async () => {
    if (!target) return
    setIsDeleting(true)
    try {
      await onConfirmed(target)
      setTarget(null)
    } catch {
      return
    } finally {
      setIsDeleting(false)
    }
  }, [onConfirmed, target])

  return {
    target,
    isOpen: target !== null,
    isDeleting,
    request,
    cancel,
    confirm,
  }
}
