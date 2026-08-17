import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Button } from '@/components/ui/Button'
import { Card, PageHeader } from '@/components/ui/Misc'
import { FolderPathField } from '@/features/patients/FolderPathField'
import { PatientForm } from '@/features/patients/PatientForm'
import {
  patientHooks,
  useApplicationFiles,
  useCreateApplication,
  useRejectApplication,
  useUpdateApplication,
} from '@/hooks/useResources'
import { cn } from '@/lib/cn'
import { rejectedCount, undecidedCount } from '@/schemas/applicationFile'
import {
  patientName,
  toPatientFormValues,
  type Patient,
} from '@/schemas/patient'
import {
  canReject,
  isReadOnly,
  type PatientApplication,
} from '@/schemas/patientApplication'
import { ApplicationSummary } from './ApplicationSummary'
import { AssigneeCard } from './AssigneeField'
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
  const [assignedTo, setAssignedTo] = useState(application?.assigned_to_id ?? '')

  // This application's source folder, not the patient's. A second
  // application for the same patient routinely draws on a different one,
  // so it is asked for here and stored on the application.
  const [folder, setFolder] = useState(application?.original_file_path ?? '')
  const [folderFiles, setFolderFiles] = useState<File[]>([])
  const [folderError, setFolderError] = useState<string | null>(null)

  const goTo = (step: StepNumber) => {
    setCurrent(step)
    if (step > furthest) setFurthest(step)
  }

  /**
   * Push the assignment at whatever exists. Before the application does,
   * the choice is just held in state and goes up with the create call.
   */
  function assign(userId: string) {
    setAssignedTo(userId)
    if (!record || userId === (record.assigned_to_id ?? '')) return

    void updateApplication
      .mutateAsync({ id: record.id, values: { assigned_to_id: userId } })
      .then(setRecord)
      .catch(() => setAssignedTo(record.assigned_to_id ?? ''))
  }

  /**
   * Step 1 needs both halves before anything is written.
   *
   * Checked before the patient is saved, not after: the patient used to
   * be created regardless and only the application waited on the
   * folder, which left a patient on file that nobody had set out to
   * create and no application pointing at them.
   */
  function stepOneIsComplete(): boolean {
    if (folder.trim()) {
      setFolderError(null)
      return true
    }
    setFolderError('Choose the folder this application’s documents come from')
    toast.error('Choose a source folder before saving the patient')
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
      // The mutation hooks toast their own message. Staying on step 1 is
      // the point: step 2 has nothing to attach documents to, and moving
      // there anyway is what produced 'create an application first'.
      return
    }

    goTo(2)
  }

  /**
   * Picking somebody off the list only fills the form in. Nothing is
   * created and nothing moves on: their details are shown to be read
   * through, corrected if they are out of date, and saved deliberately.
   * Selecting used to create the application and jump to step 2 on its
   * own, which flashed the form up for a second and left no chance to
   * check -- let alone change -- what the application was being filed
   * against.
   */
  function onPatientChosen(chosen: Patient) {
    setPatient(chosen)
  }

  /** Undo the pick, while there is still nothing filed against it. */
  function clearChosenPatient() {
    setPatient(undefined)
  }

  /** Where the batch actually landed, kept on the patient as a default. */
  function recordUploadFolder(landedIn: string) {
    if (!patient || patient.original_file_path) return

    void updatePatient
      .mutateAsync({
        id: patient.id,
        values: { ...toPatientFormValues(patient), original_file_path: landedIn },
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
  const rejected = rejectedCount(files.data ?? [])

  // Submitted: it has gone for review, and everything here is now a
  // record of what was sent rather than something still being put
  // together. Every step stays reachable -- reading it back is the
  // whole point -- and none of them offer to change anything.
  const locked = isReadOnly(record?.status)

  return (
    <div className="space-y-6">
      <PageHeader
        title={application ? 'Application' : 'New application'}
        description={
          patient
            ? // The id as well as the name: names repeat, and it is the
              // id that appears on the documents and in every email.
              `${patientName(patient)} · ${patient.id}`
            : 'Enter the patient, attach their documents, then review.'
        }
        actions={
          <Button variant="outline" onClick={() => void navigate({ to: '/applications' })}>
            Back to applications
          </Button>
        }
      />

      <StepRail
        current={current}
        furthest={locked ? 3 : furthest}
        onSelect={goTo}
      />

      {current === 1 ? (
        <div className="space-y-4">
          {locked ? (
            <Card className="p-4 text-sm text-[rgb(var(--foreground-muted))]">
              This application has been submitted. Everything below is
              shown as it was sent and cannot be changed.
            </Card>
          ) : null}

          <AssigneeCard
            value={assignedTo}
            onChange={assign}
            disabled={locked || updateApplication.isPending}
          />

          <Card className="p-5">
            <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
              Documents
            </h2>
            <div className="mt-4">
              <FolderPathField
                label="Source folder"
                required
                value={folder}
                files={folderFiles}
                disabled={locked || isSaving}
                onSelect={(path, files) => {
                  // Keep a typed-in path when the picker yields none.
                  setFolder(path || folder)
                  setFolderFiles(files)
                  if (path || files.length) setFolderError(null)
                }}
                onPathChange={(path) => {
                  setFolder(path)
                  if (path) setFolderError(null)
                }}
                {...(folderError ? { error: folderError } : {})}
                hint="Required. This application's own folder -- a later application for the same patient may use a different one. Anything selected here is uploaded in step 2."
              />
            </div>
          </Card>

          {/* Only offered while the patient is still undecided. Once one
              is attached, changing it would silently move an application
              -- and any documents already on it -- to someone else. */}
          {patient || locked ? null : (
            <PatientSourceChoice value={source} onChange={setSource} />
          )}

          {source === 'existing' && !patient && !locked ? (
            <ExistingPatientPicker onSelect={onPatientChosen} />
          ) : (
            <>
              {/* Only while the pick can still be undone -- once an
                  application exists it is filed against this patient. */}
              {source === 'existing' && patient && !record ? (
                <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
                  <p className="text-sm text-[rgb(var(--foreground-muted))]">
                    Check <strong>{patientName(patient)}</strong>'s details
                    below, correct anything out of date, then save to
                    continue.
                  </p>
                  <Button variant="outline" size="sm" onClick={clearChosenPatient}>
                    Choose a different patient
                  </Button>
                </Card>
              ) : null}

              <PatientForm
                {...(patient ? { patient } : {})}
                cancelTo="/applications"
                submitLabel={patient ? 'Save and continue' : 'Create and continue'}
                onBeforeSubmit={stepOneIsComplete}
                onSaved={onPatientSaved}
                // The application asks for its own folder above.
                showFilePath={false}
                readOnly={locked}
              />
            </>
          )}
        </div>
      ) : null}

      {current === 2 ? (
        record ? (
          <>
            <FileReviewPanel
              applicationId={record.id}
              onUploaded={recordUploadFolder}
              initialFiles={folderFiles}
              onInitialFilesTaken={() => setFolderFiles([])}
              readOnly={locked}
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
                // Recorded before leaving, so a re-render on the way out
                // shows the verdict rather than the state it replaced.
                setRecord(updated)
                // Back to the list: the decision has been made and there
                // is nothing further to do here. Rejecting again -- once
                // the first problem is fixed and the next one turns up --
                // is done by reopening it, which is where the reason for
                // the last rejection is waiting to be read anyway.
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
                {undecided === 1 ? 'needs' : 'need'} approving or rejecting in
                step 2 before this can be submitted.
              </Card>
            ) : null}

            {/* A rejected document is a decision that this batch is not
                fit to go, so the only thing left to do with the
                application is turn it down too. Submitting it anyway
                would ask the reviewer to find what was found here. */}
            {!locked && rejected > 0 ? (
              <Card className="p-5 text-sm text-[rgb(var(--foreground-muted))]">
                {rejected} document{rejected === 1 ? '' : 's'} in step 2{' '}
                {rejected === 1 ? 'has' : 'have'} been rejected, so this
                application cannot be submitted. Reject it, or clear the
                rejection in step 2 first.
              </Card>
            ) : null}

            <div className="flex flex-wrap justify-between gap-3">
              <Button variant="outline" onClick={() => goTo(2)}>
                Back to documents
              </Button>

              {/* Submitted: it is with a reviewer now. Neither pushing it
                  again nor turning it down happens from here. */}
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
