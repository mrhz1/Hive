import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Button } from '@/components/ui/Button'
import { Card, PageHeader } from '@/components/ui/Misc'
import { PatientForm } from '@/features/patients/PatientForm'
import {
  patientHooks,
  useApplicationFiles,
  useCreateApplication,
  useRejectApplication,
  useUpdateApplication,
} from '@/hooks/useResources'
import { cn } from '@/lib/cn'
import { undecidedCount } from '@/schemas/applicationFile'
import {
  patientName,
  toPatientFormValues,
  type Patient,
} from '@/schemas/patient'
import {
  canReject,
  type PatientApplication,
} from '@/schemas/patientApplication'
import { ApplicationSummary } from './ApplicationSummary'
import { ExistingPatientPicker } from './ExistingPatientPicker'
import { FileReviewPanel } from './FileReviewPanel'

const STEPS = [
  { number: 1, label: 'Patient' },
  { number: 2, label: 'Documents' },
  { number: 3, label: 'Summary' },
] as const

type StepNumber = (typeof STEPS)[number]['number']

/** The step rail. Steps ahead of the patient being saved are unreachable. */
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

type PatientSource = 'existing' | 'new'

const SOURCES = [
  {
    value: 'new' as const,
    label: 'New patient',
    hint: 'Not seen here before -- fill in their details',
  },
  {
    value: 'existing' as const,
    label: 'Existing patient',
    hint: 'Already on file -- search and pick them',
  },
]

/** Step 1's fork: is this application for somebody already on file? */
function PatientSourceChoice({
  value,
  onChange,
}: {
  value: PatientSource
  onChange: (value: PatientSource) => void
}) {
  return (
    <fieldset className="grid gap-3 sm:grid-cols-2">
      <legend className="sr-only">Is this for an existing patient?</legend>
      {SOURCES.map((source) => {
        const isSelected = source.value === value
        return (
          <button
            key={source.value}
            type="button"
            aria-pressed={isSelected}
            onClick={() => onChange(source.value)}
            className={cn(
              'rounded-xl border p-4 text-left transition-colors',
              isSelected
                ? 'border-[rgb(var(--primary))] bg-[rgb(var(--primary))]/5 ring-1 ring-[rgb(var(--primary))]'
                : 'border-[rgb(var(--border))] bg-[rgb(var(--surface))] hover:bg-[rgb(var(--surface-muted))]'
            )}
          >
            <span className="block text-sm font-semibold">{source.label}</span>
            <span className="mt-1 block text-xs text-[rgb(var(--foreground-muted))]">
              {source.hint}
            </span>
          </button>
        )
      })}
    </fieldset>
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
  const updatePatient = patientHooks.useUpdate()
  const reject = useRejectApplication()

  const [patient, setPatient] = useState<Patient | undefined>(initialPatient)
  const [source, setSource] = useState<PatientSource>('new')
  const [current, setCurrent] = useState<StepNumber>(1)
  const [furthest, setFurthest] = useState<StepNumber>(initialPatient ? 3 : 1)
  const [record, setRecord] = useState<PatientApplication | undefined>(application)
  const [rejecting, setRejecting] = useState(false)

  const goTo = (step: StepNumber) => {
    setCurrent(step)
    if (step > furthest) setFurthest(step)
  }

  async function onPatientSaved(saved: Patient) {
    setPatient(saved)

    try {
      if (record) {
        const updated = await updateApplication.mutateAsync({
          id: record.id,
          values: {},
        })
        setRecord(updated)
      } else {
        const created = await createApplication.mutateAsync({
          patient_id: saved.id,
          status: 'draft',
        })
        setRecord(created)
      }
    } catch {
      // The mutation hooks toast their own message.
    }

    goTo(2)
  }

  async function onPatientChosen(chosen: Patient) {
    await onPatientSaved(chosen)
  }

  function recordUploadFolder(folder: string) {
    if (!patient || patient.original_file_path) return

    void updatePatient
      .mutateAsync({
        id: patient.id,
        values: { ...toPatientFormValues(patient), original_file_path: folder },
      })
      .then(setPatient)
      .catch(() => undefined)
  }

  /** Step 3's submit: the application leaves draft and goes for review. */
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

  return (
    <div className="space-y-6">
      <PageHeader
        title={application ? 'Application' : 'New application'}
        description={
          patient
            ? patientName(patient)
            : 'Enter the patient, attach their documents, then review.'
        }
        actions={
          <Button variant="outline" onClick={() => void navigate({ to: '/applications' })}>
            Back to applications
          </Button>
        }
      />

      <StepRail current={current} furthest={furthest} onSelect={goTo} />

      {current === 1 ? (
        <div className="space-y-4">
          {/* Only offered while the patient is still undecided. Once one
              is attached, changing it would silently move an application
              -- and any documents already on it -- to someone else. */}
          {patient ? null : (
            <PatientSourceChoice value={source} onChange={setSource} />
          )}

          {source === 'existing' && !patient ? (
            <ExistingPatientPicker onSelect={onPatientChosen} isBusy={isSaving} />
          ) : (
            <PatientForm
              {...(patient ? { patient } : {})}
              cancelTo="/applications"
              submitLabel={patient ? 'Save and continue' : 'Create and continue'}
              onSaved={onPatientSaved}
            />
          )}
        </div>
      ) : null}

      {current === 2 ? (
        record ? (
          <>
            <FileReviewPanel
              applicationId={record.id}
              onUploaded={recordUploadFolder}
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
            Save the patient in step 1 before attaching documents -- the
            application has to exist before anything can be attached to it.
          </Card>
        )
      ) : null}

      {rejecting && record ? (
        <ReasonDialog
          title="Reject this application?"
          description="The reason is kept on the record."
          confirmLabel="Reject application"
          placeholder="e.g. consent form missing"
          isBusy={reject.isPending}
          onCancel={() => setRejecting(false)}
          onConfirm={(reason) => {
            void reject
              .mutateAsync({ id: record.id, reason })
              .then((updated) => {
                setRecord(updated)
                setRejecting(false)
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

            {undecided > 0 ? (
              <Card className="p-5 text-sm text-[rgb(var(--foreground-muted))]">
                {undecided} document{undecided === 1 ? '' : 's'} still{' '}
                {undecided === 1 ? 'needs' : 'need'} approving or rejecting in
                step 2 before this can be submitted.
              </Card>
            ) : null}
            <div className="flex flex-wrap justify-between gap-3">
              <Button variant="outline" onClick={() => goTo(2)}>
                Back to documents
              </Button>
              {record && canReject(record.status) ? (
                <Button variant="danger" onClick={() => setRejecting(true)}>
                  Reject application
                </Button>
              ) : null}
              <Button
                isLoading={isSaving}
                disabled={undecided > 0}
                title={
                  undecided > 0
                    ? `${undecided} document${undecided === 1 ? '' : 's'} still need a decision`
                    : undefined
                }
                onClick={() => void submitApplication()}
              >
                {record?.status === 'submitted' ? 'Re-submit' : 'Submit application'}
              </Button>
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
