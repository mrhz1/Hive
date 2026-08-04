import { useCallback, useState } from 'react'

/**
 * Holds the "which row is pending deletion" state for a list page, so
 * every page drives the shared ConfirmDeleteModal the same way instead of
 * re-inventing open/target/confirm bookkeeping.
 */
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
      // The mutation's onError already surfaced a toast. Keep the dialog
      // open so the user can retry or cancel deliberately.
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
