import { ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Button } from '@/components/ui/Button'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useLockdown, useUnlockApp } from '@/hooks/useResources'

/** Shown on every page while the app is locked (app/lockdown.py). */
export function LockdownBanner() {
  const { can } = usePermissions()
  const lockdown = useLockdown()
  const unlock = useUnlockApp()
  const [unlocking, setUnlocking] = useState(false)

  const state = lockdown.data
  if (!state?.locked) return null
  const manager = can('security:manage')

  return (
    <div
      role="alert"
      className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-rose-500/50 bg-rose-500/10 p-4 text-sm"
    >
      <div className="flex items-start gap-3">
        <ShieldAlert
          className="mt-0.5 size-5 shrink-0 text-rose-600"
          aria-hidden="true"
        />
        <div>
          <strong>Hive is locked because of a security incident</strong>
          {state.level ? ` (${state.level})` : ''}.{' '}
          {manager
            ? `Only security managers can work until it is unlocked. Reason: ${state.reason ?? '—'}. Locked by ${state.locked_by ?? '—'} at ${(state.locked_at ?? '').slice(0, 16).replace('T', ' ')}.`
            : 'Nothing can be opened or changed until it is unlocked. Contact the application specialist.'}
        </div>
      </div>
      {manager ? (
        <Button size="sm" variant="outline" onClick={() => setUnlocking(true)}>
          Unlock
        </Button>
      ) : null}
      {unlocking ? (
        <ReasonDialog
          title="Unlock Hive?"
          description="Everyone can use the app again. The reason is emailed and kept in the audit log."
          confirmLabel="Unlock"
          placeholder="e.g. account disabled, no further access seen"
          isBusy={unlock.isPending}
          onCancel={() => setUnlocking(false)}
          onConfirm={(reason) =>
            void unlock
              .mutateAsync(reason)
              .then(() => setUnlocking(false))
              .catch(() => undefined)
          }
        />
      ) : null}
    </div>
  )
}
