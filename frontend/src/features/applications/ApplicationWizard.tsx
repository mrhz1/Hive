import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Button } from '@/components/ui/Button'
import { Card, PageHeader } from '@/components/ui/Misc'
import { PatientForm } from '@/features/patients/PatientForm'
import {
  useApplicationFiles,
  useCreateApplication,
  useRejectApplication,
  useUpdateApplication,
} from '@/hooks/useResources'
import { patientsApi } from '@/lib/api/resources'
import { cn } from '@/lib/cn'
import type { AvailableCode } from '@/schemas/intake'
import { rejectedCount, undecidedCount } from '@/schemas/applicationFile'
import { patientName, type Patient } from '@/schemas/patient'
import {
  canReject,
  isReadOnly,
  type PatientApplication,
} from '@/schemas/patientApplication'
import { ApplicationSummary } from './ApplicationSummary'
import { AssigneeCard } from './AssigneeField'
import { FileReviewPanel } from './FileReviewPanel'
import { IntakeCodePicker } from './IntakeCodePicker'
import { IntakeFilePicker } from './IntakeFilePicker'

const STEPS = [
  { number: 1, label: 'Patient' },
  { number: 2, label: 'Documents' },
  { number: 3, label: 'Summary' },
] as const

type StepNumber = (typeof STEPS)[number]['number']

function StepRail({
  current,
  furthest,
  onSelect,
}: {
  current: StepNumber
  furthest: StepNumber
  onSelect: (step: StepNumber) => void
}) {
  return (
    <ol className="flex flex-wrap gap-2" aria-label="Application steps">
      {STEPS.map((step) => {
        const reachable = step.number <= furthest
        return (
          <li key={step.number}>
            <button
              type="button"
              disabled={!reachable}
              aria-current={step.number === current ? 'step' : undefined}
              onClick={() => onSelect(step.number)}
              className={cn(
                'rounded-lg border px-4 py-2 text-sm font-semibold transition-colors',
                step.number === current
                  ? 'border-transparent bg-[rgb(var(--primary))] text-[rgb(var(--primary-foreground))]'
                  : 'border-[rgb(var(--border))] bg-[rgb(var(--surface))]',
                reachable ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'
              )}
            >
              <span className="tabular-nums">{step.number}.</span> {step.label}
            </button>
          </li>
        )
      })}
    </ol>
  )
}

export function ApplicationWizard({
  application,
  initialPatient,
}: {
  application?: PatientApplication
  initialPatient?: Patient
}) {
  const navigate = useNavigate()
  const createApplication = useCreateApplication()
  const updateApplication = useUpdateApplication()
  const reject = useRejectApplication()

  const [patient, setPatient] = useState<Patient | undefined>(initialPatient)
  const [current, setCurrent] = useState<StepNumber>(1)
  const [furthest, setFurthest] = useState<StepNumber>(initialPatient ? 3 : 1)
  const [record, setRecord] = useState<PatientApplication | undefined>(application)
  const [rejecting, setRejecting] = useState(false)
  const [assignedTo, setAssignedTo] = useState(application?.assigned_to_id ?? '')

  const [folder, setFolder] = useState(application?.original_file_path ?? '')

  const [code, setCode] = useState<string | undefined>(
    application?.patient_id ?? initialPatient?.id
  )
  const [choosingCode, setChoosingCode] = useState(false)

  const goTo = (step: StepNumber) => {
    setCurrent(step)
    if (step > furthest) setFurthest(step)
  }

  function assign(userId: string) {
    setAssignedTo(userId)
    if (!record || userId === (record.assigned_to_id ?? '')) return

    void updateApplication
      .mutateAsync({ id: record.id, values: { assigned_to_id: userId } })
      .then(setRecord)
      .catch(() => setAssignedTo(record.assigned_to_id ?? ''))
  }

  function stepOneIsComplete(): boolean {
    if (folder.trim()) return true
    toast.error('Choose a patient code before saving the patient')
    return false
  }

  async function onPatientSaved(saved: Patient) {
    setPatient(saved)

    let current: PatientApplication | undefined
    try {
      if (record) {
        current = await updateApplication.mutateAsync({
          id: record.id,
          values: { assigned_to_id: assignedTo, original_file_path: folder },
        })
      } else {
        current = await createApplication.mutateAsync({
          patient_id: saved.id,
          status: 'draft',
          assigned_to_id: assignedTo,
          original_file_path: folder,
        })
      }
      setRecord(current)
    } catch {
      return
    }

    goTo(2)
  }

  async function onCodeChosen(chosen: AvailableCode) {
    setCode(chosen.code)
    setFolder(chosen.folder)

    if (!chosen.patient_exists) {
      setPatient(undefined)
      return
    }

    setChoosingCode(true)
    try {
      setPatient(await patientsApi.get(chosen.code))
    } catch {
      toast.error(`Could not load patient ${chosen.code}`)
    } finally {
      setChoosingCode(false)
    }
  }

  async function submitApplication() {
    if (!record) {
      toast.error('This application has not been created yet')
      return
    }
    try {
      await updateApplication.mutateAsync({
        id: record.id,
        values: { status: 'submitted' },
      })
      toast.success('Application submitted')
      await navigate({ to: '/applications' })
    } catch {
      // Toasted by the hook.
    }
  }

  const isSaving = createApplication.isPending || updateApplication.isPending

  const files = useApplicationFiles(record?.id ?? '', Boolean(record))
  const undecided = undecidedCount(files.data ?? [])
  const rejected = rejectedCount(files.data ?? [])

  const locked = isReadOnly(record?.status)

  return (
    <div className="space-y-6">
      <PageHeader
        title={application ? 'Application' : 'New application'}
        description={
          patient
            ? `${patientName(patient)} · ${patient.id}`
            : 'Enter the patient, attach their documents, then review.'
        }
        actions={
          <Button
            variant="outline"
            onClick={() => void navigate({ to: '/applications' })}
          >
            Back to applications
          </Button>
        }
      />

      <StepRail current={current} furthest={locked ? 3 : furthest} onSelect={goTo} />

      {current === 1 ? (
        <div className="space-y-4">
          {record?.status === 'deleted' ? (
            <Card className="border-rose-500/40 p-4 text-sm">
              <strong>This application was deleted.</strong> Its documents were removed
              {record.status_reason ? ` (${record.status_reason})` : ''}. Only this record
              is kept; it cannot be opened or changed.
            </Card>
          ) : locked ? (
            <Card className="p-4 text-sm text-[rgb(var(--foreground-muted))]">
              This application has been submitted. Everything below is shown as it was
              sent and cannot be changed.
            </Card>
          ) : null}

          <AssigneeCard
            value={assignedTo}
            onChange={assign}
            disabled={locked || updateApplication.isPending}
          />

          {record ? (
            <Card className="p-4 text-sm">
              For patient code{' '}
              <span className="font-mono text-base font-bold">{code}</span>
              <span className="text-[rgb(var(--foreground-muted))]">
                {' '}
                -- fixed once the application exists.
              </span>
            </Card>
          ) : (
            <IntakeCodePicker
              value={code}
              onChoose={(chosen) => void onCodeChosen(chosen)}
              disabled={locked || isSaving || choosingCode}
            />
          )}

          {code && !choosingCode ? (
            <>
              {!patient ? (
                <Card className="p-4 text-sm text-[rgb(var(--foreground-muted))]">
                  No patient has code <strong className="font-mono">{code}</strong> yet.
                  Fill in what you know and it is created with that code.
                </Card>
              ) : null}
              <PatientForm
                key={code}
                {...(patient ? { patient } : { code })}
                cancelTo="/applications"
                submitLabel={patient ? 'Save and continue' : 'Create and continue'}
                onBeforeSubmit={stepOneIsComplete}
                onSaved={onPatientSaved}
                readOnly={locked}
              />
            </>
          ) : null}
        </div>
      ) : null}

      {current === 2 ? (
        record ? (
          <>
            {!locked && patient ? (
              <IntakeFilePicker applicationId={record.id} code={patient.id} />
            ) : null}
            <FileReviewPanel
              applicationId={record.id}
              readOnly={locked}
              deleted={record.status === 'deleted'}
            />
            <div className="flex flex-wrap justify-between gap-3">
              <Button variant="outline" onClick={() => goTo(1)}>
                Back to patient
              </Button>
              <Button onClick={() => goTo(3)}>Continue to summary</Button>
            </div>
          </>
        ) : (
          <Card className="p-5 text-sm text-[rgb(var(--foreground-muted))]">
            Save the patient in step 1 before attaching documents, the application has to
            exist before anything can be attached to it.
          </Card>
        )
      ) : null}

      {rejecting && record ? (
        <ReasonDialog
          title={
            record.status === 'rejected'
              ? 'Reject this application again?'
              : 'Reject this application?'
          }
          description={
            record.status === 'rejected'
              ? 'The new reason replaces the one on the record, so say what is wrong now.'
              : 'The reason is kept on the record.'
          }
          confirmLabel="Reject application"
          placeholder="e.g. consent form missing"
          isBusy={reject.isPending}
          onCancel={() => setRejecting(false)}
          onConfirm={(reason) => {
            void reject
              .mutateAsync({ id: record.id, reason })
              .then(async (updated) => {
                setRejecting(false)

                setRecord(updated)

                await navigate({ to: '/applications' })
              })
              .catch(() => undefined)
          }}
        />
      ) : null}

      {current === 3 ? (
        patient ? (
          <>
            <ApplicationSummary
              patient={patient}
              {...(record ? { application: record } : {})}
            />

            {!locked && undecided > 0 ? (
              <Card className="p-5 text-sm text-[rgb(var(--foreground-muted))]">
                {undecided} document{undecided === 1 ? '' : 's'} still{' '}
                {undecided === 1 ? 'is' : 'are'} not approved yet, so this cannot be
                submitted.
              </Card>
            ) : null}

            {}
            {!locked && rejected > 0 ? (
              <Card className="p-5 text-sm text-[rgb(var(--foreground-muted))]">
                {rejected} document{rejected === 1 ? '' : 's'} in step 2{' '}
                {rejected === 1 ? 'has' : 'have'} been rejected, so this application
                cannot be submitted. Replace the de-identified copy from Rejections,
                delete the document in step 2, or reject the application.
              </Card>
            ) : null}

            <div className="flex flex-wrap justify-between gap-3">
              <Button variant="outline" onClick={() => goTo(2)}>
                Back to documents
              </Button>

              {}
              {locked ? (
                <Button onClick={() => void navigate({ to: '/applications' })}>
                  Close
                </Button>
              ) : (
                <>
                  {record && canReject(record.status) ? (
                    <Button variant="danger" onClick={() => setRejecting(true)}>
                      {record.status === 'rejected'
                        ? 'Reject again'
                        : 'Reject application'}
                    </Button>
                  ) : null}
                  <Button
                    isLoading={isSaving}
                    disabled={undecided > 0 || rejected > 0}
                    title={
                      undecided > 0
                        ? `${undecided} document${undecided === 1 ? '' : 's'} still need a decision`
                        : rejected > 0
                          ? `${rejected} document${rejected === 1 ? '' : 's'} rejected in step 2`
                          : undefined
                    }
                    onClick={() => void submitApplication()}
                  >
                    Submit application
                  </Button>
                </>
              )}
            </div>
          </>
        ) : (
          <Card className="p-5 text-sm text-[rgb(var(--foreground-muted))]">
            Save the patient in step 1 before reviewing.
          </Card>
        )
      ) : null}
    </div>
  )
}
