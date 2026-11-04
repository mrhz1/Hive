import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge, Card } from '@/components/ui/Misc'
import { ApiError } from '@/lib/api/client'
import { consentsApi } from '@/lib/api/resources'
import type { WithdrawalPreview, WithdrawalResult } from '@/schemas/qc'

const muted = 'text-xs text-[rgb(var(--foreground-muted))]'

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

/** Delete a patient's data after research consent is withdrawn (protocol 6.7). */
export function WithdrawalCard() {
  const client = useQueryClient()
  const [code, setCode] = useState('')
  const [preview, setPreview] = useState<WithdrawalPreview | null>(null)
  const [result, setResult] = useState<WithdrawalResult | null>(null)
  const [confirming, setConfirming] = useState(false)

  const check = useMutation({
    mutationFn: (value: string) => consentsApi.withdrawalPreview(value),
    onSuccess: (data) => {
      setPreview(data)
      setResult(null)
    },
    onError: (error) => {
      setPreview(null)
      toast.error(message(error, 'Could not check the patient'))
    },
  })

  const purge = useMutation({
    mutationFn: (v: { code: string; reason: string }) =>
      consentsApi.withdraw(v.code, v.reason),
    onSuccess: (data) => {
      setConfirming(false)
      setPreview(null)
      setResult(data)
      toast.success(`${data.patient_id}: data deleted`)
      void client.invalidateQueries()
    },
    onError: (error) => toast.error(message(error, 'Could not delete the data')),
  })

  const live = preview?.projects.filter((p) => !p.ended) ?? []
  const released = preview?.projects.filter((p) => p.released.length > 0) ?? []
  const problems = preview
    ? Object.values(preview.problem_files).reduce((a, b) => a + b, 0)
    : 0

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="text-sm font-bold">Delete data after a withdrawal</h2>
        <p className={muted}>
          For a patient whose latest research consent is withdrawn or refused. Record the
          decision above first, then check what will be deleted. The patient record and
          the consent history are kept, so the withdrawal stays on file and the patient
          can't be picked again.
        </p>
      </div>

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (code.trim()) check.mutate(code.trim().toUpperCase())
        }}
      >
        <div className="w-64">
          <TextField
            label="Patient code"
            placeholder="AVSD0161"
            value={code}
            onChange={(event) => {
              setCode(event.target.value)
              setPreview(null)
            }}
          />
        </div>
        <Button
          type="submit"
          variant="outline"
          disabled={!code.trim()}
          isLoading={check.isPending}
          leadingIcon={<Search className="size-4" aria-hidden="true" />}
        >
          Check what will be deleted
        </Button>
      </form>

      {preview ? (
        <div className="space-y-3 rounded-lg border border-[rgb(var(--border))] p-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono font-semibold">{preview.patient_id}</span>
            <Badge tone={preview.allowed ? 'danger' : 'neutral'}>
              research consent {preview.consent_status ?? 'not recorded'}
              {preview.consent_date ? ` on ${preview.consent_date}` : ''}
            </Badge>
          </div>

          {!preview.allowed ? (
            <p className="text-sm">{preview.blocked_reason}</p>
          ) : (
            <>
              <ul className="list-disc space-y-1 pl-5">
                <li>
                  <strong>{preview.documents}</strong> document(s) in{' '}
                  {preview.applications.length} application(s): originals, de-identified
                  copies and their metadata. The applications are marked deleted.
                </li>
                <li>
                  <strong>{problems}</strong> file(s) waiting in “need attention” or
                  “failed”.
                </li>
                <li>
                  <strong>{preview.redcap_values}</strong> REDCap value(s).
                </li>
                {live.map((p) => (
                  <li key={p.id}>
                    Project <strong>{p.short_code}</strong> ({p.name}): taken out of the
                    cohort ({p.project_patient_id})
                    {p.workspace
                      ? p.cohort_size > 1
                        ? ', workspace rebuilt without them'
                        : ', workspace deleted (nobody left)'
                      : ''}
                    {p.pending_releases.length
                      ? `, ${p.pending_releases.length} release(s) waiting for review rejected`
                      : ''}
                    .
                  </li>
                ))}
                {preview.abstraction_folders.map((f) => (
                  <li key={f.id}>
                    Abstraction folder <strong>{f.name}</strong>: {f.documents} of{' '}
                    {f.total} document(s) removed
                    {f.documents >= f.total ? ' (the folder is deleted)' : ''}.
                  </li>
                ))}
              </ul>

              {released.length > 0 ? (
                <div
                  role="alert"
                  className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3"
                >
                  <strong>Already released to Zone 2, can't be recalled:</strong>{' '}
                  {released
                    .map((p) => `${p.short_code} (${p.released.length} release(s))`)
                    .join(', ')}
                  . Tell those projects' researchers to delete this patient (project ID{' '}
                  {released.map((p) => p.project_patient_id).join(', ')}).
                </div>
              ) : null}

              <Button
                variant="danger"
                leadingIcon={<Trash2 className="size-4" aria-hidden="true" />}
                onClick={() => setConfirming(true)}
              >
                Delete {preview.patient_id}'s data
              </Button>
            </>
          )}
        </div>
      ) : null}

      {result ? (
        <div
          role="status"
          className="space-y-1 rounded-lg border border-[rgb(var(--border))] p-4 text-sm"
        >
          <p>
            <strong>{result.patient_id}</strong>: deleted {result.documents} document(s)
            in {result.applications} application(s), {result.problem_files} waiting
            file(s) and {result.redcap_values} REDCap value(s).
          </p>
          {result.projects.map((p) => (
            <p key={p.short_code}>
              {p.short_code}: out of the cohort
              {p.workspace ? `, workspace ${p.workspace}` : ''}
              {p.releases_rejected ? `, ${p.releases_rejected} release(s) rejected` : ''}.
            </p>
          ))}
          {result.abstraction_folders.map((f) => (
            <p key={f.name}>
              Abstraction folder {f.name}: {f.result}.
            </p>
          ))}
          {result.already_released.length > 0 ? (
            <p className="font-medium">
              Still in Zone 2:{' '}
              {result.already_released.map((r) => r.short_code).join(', ')}.
            </p>
          ) : null}
        </div>
      ) : null}

      {confirming && preview ? (
        <ReasonDialog
          title={`Delete ${preview.patient_id}'s data`}
          description="This deletes the documents and data listed and cannot be undone. The reason is kept in the audit log."
          confirmLabel="Delete data"
          placeholder="e.g. withdrawal form received 2026-11-03"
          isBusy={purge.isPending}
          onConfirm={(reason) => purge.mutate({ code: preview.patient_id, reason })}
          onCancel={() => setConfirming(false)}
        />
      ) : null}
    </Card>
  )
}
