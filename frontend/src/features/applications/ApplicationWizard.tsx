import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Card, PageHeader } from '@/components/ui/Misc'
import { PatientForm } from '@/features/patients/PatientForm'
import {
  useCreateApplication,
  useUpdateApplication,
} from '@/hooks/useResources'
import { cn } from '@/lib/cn'
import { patientName, type Patient } from '@/schemas/patient'
import type { PatientApplication } from '@/schemas/patientApplication'
import { ApplicationSummary } from './ApplicationSummary'
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

/**
 * Create or continue an application.
 *
 * Step 1 is the patient form itself: saving it creates (or updates) the
 * patient *and* the application row alongside it, so the two never drift
 * apart. Steps 2 and 3 need a saved patient to hang documents off, which
 * is why they stay locked until step 1 succeeds.
 */
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

  // Resuming an existing application starts past step 1, because its
  // patient already exists.
  const [patient, setPatient] = useState<Patient | undefined>(initialPatient)
  const [current, setCurrent] = useState<StepNumber>(1)
  const [furthest, setFurthest] = useState<StepNumber>(initialPatient ? 3 : 1)
  const [record, setRecord] = useState<PatientApplication | undefined>(application)

  const goTo = (step: StepNumber) => {
    setCurrent(step)
    if (step > furthest) setFurthest(step)
  }

  /**
   * Step 1's save. The patient write already happened inside PatientForm;
   * this is the application row that goes with it.
   *
   * A failure here is reported but does not block the wizard: the patient
   * is saved either way, and pretending otherwise would leave the user
   * re-entering a record that already exists.
   */
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
        <PatientForm
          {...(patient ? { patient } : {})}
          cancelTo="/applications"
          submitLabel={patient ? 'Save and continue' : 'Create and continue'}
          onSaved={onPatientSaved}
        />
      ) : null}

      {current === 2 ? (
        patient ? (
          <>
            <FileReviewPanel patientId={patient.id} />
            <div className="flex flex-wrap justify-between gap-3">
              <Button variant="outline" onClick={() => goTo(1)}>
                Back to patient
              </Button>
              <Button onClick={() => goTo(3)}>Continue to summary</Button>
            </div>
          </>
        ) : (
          <Card className="p-5 text-sm text-[rgb(var(--foreground-muted))]">
            Save the patient in step 1 before attaching documents.
          </Card>
        )
      ) : null}

      {current === 3 ? (
        patient ? (
          <>
            <ApplicationSummary
              patient={patient}
              {...(record ? { application: record } : {})}
            />
            <div className="flex flex-wrap justify-between gap-3">
              <Button variant="outline" onClick={() => goTo(2)}>
                Back to documents
              </Button>
              <Button isLoading={isSaving} onClick={() => void submitApplication()}>
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
