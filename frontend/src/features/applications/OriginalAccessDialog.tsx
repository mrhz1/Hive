import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { SelectField, TextAreaField } from '@/components/ui/Field'
import { Badge } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import {
  useGrantOriginal,
  useOriginalGrants,
  useRevokeOriginal,
  useUserDirectory,
} from '@/hooks/useResources'

export function OriginalAccessDialog({
  fileId,
  fileName,
  onClose,
}: {
  fileId: string
  fileName: string
  onClose: () => void
}) {
  const grants = useOriginalGrants(fileId)
  const { data: people = [] } = useUserDirectory()
  const grant = useGrantOriginal(fileId)
  const revoke = useRevokeOriginal(fileId)
  const [person, setPerson] = useState('')
  const [reason, setReason] = useState('')

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const active = (grants.data ?? []).filter((g) => !g.revoked_at)
  const past = (grants.data ?? []).filter((g) => g.revoked_at)
  const holders = new Set(active.map((g) => g.user_id))

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Access to the original"
    >
      <div className="max-h-[90vh] w-full max-w-lg space-y-4 overflow-y-auto rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-5 shadow-xl">
        <div>
          <h2 className="text-sm font-bold">Access to the original</h2>
          <p className="mt-1 text-xs break-all text-[rgb(var(--foreground-muted))]">
            {fileName}
          </p>
          <p className="mt-2 text-xs text-[rgb(var(--foreground-muted))]">
            Archived originals still carry the patient's identity. Give access only when
            the redacted copy looks damaged and the original is needed to check it. Every
            grant and every opening is logged.
          </p>
        </div>

        {grants.isLoading ? (
          <Spinner label="Loading access" />
        ) : (
          <div className="space-y-2">
            {active.length === 0 ? (
              <p className="text-sm text-[rgb(var(--foreground-muted))]">
                Nobody can open this original.
              </p>
            ) : (
              <ul className="divide-y divide-[rgb(var(--border))] rounded-lg border border-[rgb(var(--border))] text-sm">
                {active.map((g) => (
                  <li key={g.id} className="flex items-start justify-between gap-3 p-3">
                    <div className="min-w-0">
                      <p className="font-semibold">{g.username ?? g.user_id}</p>
                      <p className="text-xs text-[rgb(var(--foreground-muted))]">
                        {g.reason}
                      </p>
                      <p className="text-[11px] text-[rgb(var(--foreground-muted))]">
                        by {g.granted_by_username ?? '—'},{' '}
                        {(g.granted_at ?? '').slice(0, 10)}
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      isLoading={revoke.isPending && revoke.variables === g.id}
                      onClick={() => revoke.mutate(g.id)}
                    >
                      Take back
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {past.length > 0 ? (
              <p className="text-[11px] text-[rgb(var(--foreground-muted))]">
                Taken back earlier:{' '}
                {past.map((g) => (
                  <Badge key={g.id} tone="neutral" className="mr-1">
                    {g.username ?? g.user_id}
                  </Badge>
                ))}
              </p>
            ) : null}
          </div>
        )}

        <div className="space-y-3 border-t border-[rgb(var(--border))] pt-4">
          <SelectField
            label="Give access to"
            value={person}
            placeholder="Pick a person"
            options={people
              .filter((p) => p.is_active && !holders.has(p.id))
              .map((p) => ({
                value: p.id,
                label: `${p.first_name} ${p.last_name} (${p.username})`,
              }))}
            onChange={(event) => setPerson(event.target.value)}
          />
          <TextAreaField
            label="Why"
            required
            rows={2}
            value={reason}
            placeholder="e.g. a syndrome named after a clinician was redacted on page 3"
            onChange={(event) => setReason(event.target.value)}
          />
        </div>

        <div className="flex justify-end gap-3">
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button
            disabled={!person || !reason.trim()}
            isLoading={grant.isPending}
            onClick={() =>
              void grant
                .mutateAsync({ userId: person, reason: reason.trim() })
                .then(() => {
                  setPerson('')
                  setReason('')
                })
                .catch(() => undefined)
            }
          >
            Give access
          </Button>
        </div>
      </div>
    </div>
  )
}
