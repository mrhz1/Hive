import { useNavigate } from '@tanstack/react-router'
import { type ReactNode } from 'react'
import { FormLayout, FullWidth } from '@/components/FormLayout'
import { TextField } from '@/components/ui/Field'
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
import { FolderPathField } from './FolderPathField'

/**
 * A labelled band across the two-column form grid.
 *
 * The record holds three unrelated blocks of contact details -- the
 * patient's own, the provider's, and the stored documents -- and without
 * the headings `street` and `ptstreet` are indistinguishable in the UI.
 */
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

/**
 * Same component for create and edit -- see UserForm for the rationale.
 *
 * Also serves as step 1 of the application wizard, which needs the saved
 * record rather than a redirect: passing `onSaved` replaces the navigate
 * to /patients, so the wizard can carry the patient into step 2. The
 * fields, validation and upload behaviour are identical either way.
 */
export function PatientForm({
  patient,
  onSaved,
  cancelTo = '/patients',
  submitLabel,
}: {
  patient?: Patient
  onSaved?: (patient: Patient) => void | Promise<void>
  cancelTo?: string
  submitLabel?: string
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
      footerNote={
        patient
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

      <Section
        title="Source documents"
        hint="Where this patient's documents live. The path is recorded on the record; the documents themselves are attached to an application, in step 2 of the wizard."
      />
      <FullWidth>
        <FolderPathField
          label="Original file path"
          required
          value={watch('original_file_path')}
          // Path only. Documents belong to an application, which does not
          // exist yet at this point in the wizard -- they are uploaded in
          // step 2, against the application row step 1 creates.
          files={[]}
          disabled={isSubmitting}
          error={errors.original_file_path?.message}
          hint="Choose a folder to include everything inside it."
          onSelect={(path, files) => {
            // A multi-file pick yields no derivable folder, so an empty
            // path leaves a previously chosen one alone rather than
            // clearing a valid value. Clear does send '' with no files.
            if (path || files.length === 0) {
              setValue('original_file_path', path, { shouldValidate: true })
            }
          }}
        />
      </FullWidth>
      <FullWidth>
        <FolderPathField
          label="De-identified file path"
          value={watch('deidentified_file_path')}
          // Path only: the redacted copies are produced by the OCR job,
          // so pointing at them must not also re-upload them as new
          // patient documents.
          files={[]}
          disabled={isSubmitting}
          error={errors.deidentified_file_path?.message}
          hint="Where the redacted copies live. Usually filled in by the de-identification job."
          onSelect={(path, files) => {
            if (path || files.length === 0) {
              setValue('deidentified_file_path', path, { shouldValidate: true })
            }
          }}
        />
      </FullWidth>

      <Section title="Record" />
      <TextField
        label="Registration date"
        type="date"
        error={errors.dt_reg?.message}
        {...register('dt_reg')}
      />
    </FormLayout>
  )
}
