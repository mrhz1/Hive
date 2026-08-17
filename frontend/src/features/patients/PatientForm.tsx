import { useNavigate } from '@tanstack/react-router'
import { type ReactNode } from 'react'
import { FormLayout, FullWidth } from '@/components/FormLayout'
import { TextField } from '@/components/ui/Field'
import { FolderPathField } from '@/features/patients/FolderPathField'
import { applyServerErrors, useApiForm } from '@/hooks/useApiForm'
import { patientHooks } from '@/hooks/useResources'
import {
  EMPTY_PATIENT_FORM,
  PATIENT_FIELD_NAMES,
  patientFormSchema,
  patientName,
  toPatientFormValues,
  type Patient,
  type PatientFormValues,
} from '@/schemas/patient'

function Section({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <FullWidth>
      <div className="border-t border-[rgb(var(--border))] pt-6 first:border-0 first:pt-0">
        <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
          {title}
        </h2>
        {hint ? (
          <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">{hint}</p>
        ) : null}
      </div>
    </FullWidth>
  )
}

export function PatientForm({
  patient,
  onSaved,
  onBeforeSubmit,
  cancelTo = '/patients',
  submitLabel,
  showFilePath = true,
  readOnly = false,
}: {
  patient?: Patient
  onSaved?: (patient: Patient) => void | Promise<void>
  /**
   * A last word from the owner of this form before anything is written.
   * Returning false stops the save. The wizard uses it to refuse a
   * patient whose application has nowhere to draw documents from --
   * without it the patient was created and the application was not,
   * which left a record of somebody nobody had asked to create.
   */
  onBeforeSubmit?: () => boolean
  cancelTo?: string
  submitLabel?: string
  /**
   * The patient's own default folder, optional. The wizard hides it and
   * asks for a folder of its own instead -- that one belongs to the
   * application and is required there.
   */
  showFilePath?: boolean
  /** Show the details without offering to change them. */
  readOnly?: boolean
}) {
  const mode = patient ? 'edit' : 'create'
  const navigate = useNavigate()

  const create = patientHooks.useCreate()
  const update = patientHooks.useUpdate()

  const form = useApiForm(
    patientFormSchema,
    patient ? toPatientFormValues(patient) : EMPTY_PATIENT_FORM
  )
  const {
    register,
    handleSubmit,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = form

  const isSubmitting = create.isPending || update.isPending

  const onSubmit = handleSubmit(async (values) => {
    // Before the mutation, not after: whatever else has to be true is
    // still true while nothing has been written.
    if (onBeforeSubmit && !onBeforeSubmit()) return

    let saved: Patient

    try {
      saved = patient
        ? await update.mutateAsync({ id: patient.id, values })
        : await create.mutateAsync(values)
    } catch (error) {
      applyServerErrors<PatientFormValues>(error, setError, PATIENT_FIELD_NAMES)
      return
    }

    if (onSaved) {
      await onSaved(saved)
      return
    }
    await navigate({ to: '/patients' })
  })

  return (
    <FormLayout
      mode={mode}
      entityLabel="patient"
      cancelTo={cancelTo}
      submitLabel={submitLabel}
      isSubmitting={isSubmitting}
      onSubmit={onSubmit}
      readOnly={readOnly}
      footerNote={
        readOnly
          ? `${patient ? patientName(patient) : 'This patient'}'s details, as they stand. They cannot be changed from here.`
          : patient
            ? `Editing ${patientName(patient)}`
            : 'An original file path and at least one of first name, last name or email are required. The patient email and phone must be unique.'
      }
    >
      <Section
        title="Patient"
        hint="At least one of first name, last name or email is required -- everything else may be left blank."
      />
      <TextField
        label="First name"
        error={errors.fstname?.message}
        {...register('fstname')}
      />
      <TextField
        label="Last name"
        error={errors.lstname?.message}
        {...register('lstname')}
      />
      <TextField
        label="Date of birth"
        type="date"
        error={errors.dt_b?.message}
        {...register('dt_b')}
      />
      <TextField
        label="Date of death"
        type="date"
        error={errors.dt_d?.message}
        {...register('dt_d')}
      />
      <TextField
        label="Email"
        type="email"
        autoComplete="off"
        placeholder="patient@example.com"
        error={errors.ptemail?.message}
        {...register('ptemail')}
      />
      <TextField
        label="Phone"
        autoComplete="off"
        placeholder="+1 555 010 0100"
        error={errors.ptphone?.message}
        {...register('ptphone')}
      />
      <TextField
        label="Phone 2"
        autoComplete="off"
        error={errors.ptphone2?.message}
        {...register('ptphone2')}
      />
      <TextField
        label="Work phone"
        autoComplete="off"
        error={errors.ptwphone?.message}
        {...register('ptwphone')}
      />
      <TextField
        label="Work phone 2"
        autoComplete="off"
        error={errors.ptwphone2?.message}
        {...register('ptwphone2')}
      />
      <div className="hidden sm:block" aria-hidden="true" />
      <FullWidth>
        <TextField
          label="Street"
          placeholder="1 Elm St"
          error={errors.ptstreet?.message}
          {...register('ptstreet')}
        />
      </FullWidth>
      <TextField
        label="Street 2"
        error={errors.ptstreet2?.message}
        {...register('ptstreet2')}
      />
      <TextField
        label="Street 3"
        error={errors.ptstreet3?.message}
        {...register('ptstreet3')}
      />
      <TextField label="City" error={errors.ptcity?.message} {...register('ptcity')} />
      <TextField label="State" error={errors.ptstate?.message} {...register('ptstate')} />
      <TextField label="ZIP" error={errors.ptzip?.message} {...register('ptzip')} />
      <TextField
        label="Country"
        error={errors.ptcountry?.message}
        {...register('ptcountry')}
      />

      <Section
        title="Provider / institution"
        hint="The practice this patient is registered with."
      />
      <TextField
        label="Institution code"
        error={errors.instcode?.message}
        {...register('instcode')}
      />
      <TextField
        label="Provider name"
        error={errors.pname?.message}
        {...register('pname')}
      />
      <TextField
        label="Provider email"
        type="email"
        autoComplete="off"
        error={errors.pemail?.message}
        {...register('pemail')}
      />
      <div className="hidden sm:block" aria-hidden="true" />
      <TextField
        label="Phone 1"
        autoComplete="off"
        error={errors.phone1?.message}
        {...register('phone1')}
      />
      <TextField
        label="Phone 2"
        autoComplete="off"
        error={errors.phone2?.message}
        {...register('phone2')}
      />
      <TextField
        label="Work phone 1"
        autoComplete="off"
        error={errors.wphone1?.message}
        {...register('wphone1')}
      />
      <TextField
        label="Work phone 2"
        autoComplete="off"
        error={errors.wphone2?.message}
        {...register('wphone2')}
      />
      <FullWidth>
        <TextField
          label="Street"
          placeholder="1 Medical Plaza"
          error={errors.street?.message}
          {...register('street')}
        />
      </FullWidth>
      <TextField
        label="Street 2"
        error={errors.street2?.message}
        {...register('street2')}
      />
      <TextField
        label="Street 3"
        error={errors.street3?.message}
        {...register('street3')}
      />
      <TextField label="City" error={errors.city?.message} {...register('city')} />
      <TextField label="State" error={errors.state?.message} {...register('state')} />
      <TextField label="ZIP" error={errors.zip?.message} {...register('zip')} />
      <TextField
        label="Country"
        error={errors.country?.message}
        {...register('country')}
      />

      <Section title="Record" />
      <TextField
        label="Registration date"
        type="date"
        error={errors.dt_reg?.message}
        {...register('dt_reg')}
      />

      {showFilePath ? (
        <FullWidth>
          <FolderPathField
            label="Source folder"
            value={watch('original_file_path') ?? ''}
            files={[]}
            disabled={isSubmitting}
            onSelect={(path) =>
              setValue('original_file_path', path, { shouldDirty: true })
            }
            onPathChange={(path) =>
              setValue('original_file_path', path, { shouldDirty: true })
            }
            error={errors.original_file_path?.message}
            hint="Optional. Where this patient's documents usually come from -- an application picks its own folder, which may be a different one."
          />
        </FullWidth>
      ) : null}
    </FormLayout>
  )
}
