import { z } from 'zod'
import { idSchema } from './common'

/**
 * Naming follows the source records, and mirrors app/schemas.py::Patient:
 *   p* / unprefixed address+phone -- the provider / institution
 *   pt*                           -- the patient's own contact details
 *   fstname / lstname             -- the patient's name
 *   dt_reg / dt_b / dt_d          -- registration, birth, death
 *
 * Only original_file_path and one of fstname/lstname/ptemail are
 * required; the rest are nullable because these records come from
 * systems that do not always populate them.
 */

/** A nullable STRING column. Absent and empty both mean "unknown". */
const text = z.string().nullable().optional()

/** Hive DATE, serialised by the API as 'YYYY-MM-DD'. */
const dateText = z.string().nullable().optional()

export const patientSchema = z.object({
  id: idSchema,

  // provider / institution
  instcode: text,
  pname: text,
  pemail: text,
  phone1: text,
  phone2: text,
  wphone1: text,
  wphone2: text,
  street: text,
  street2: text,
  street3: text,
  city: text,
  state: text,
  zip: text,
  country: text,

  // patient
  fstname: text,
  lstname: text,
  ptemail: text,
  ptphone: text,
  ptphone2: text,
  ptwphone: text,
  ptwphone2: text,
  ptstreet: text,
  ptstreet2: text,
  ptstreet3: text,
  ptcity: text,
  ptstate: text,
  ptzip: text,
  ptcountry: text,

  // dates
  dt_reg: dateText,
  dt_b: dateText,
  dt_d: dateText,

  // source documents recorded on the patient itself, alongside the
  // per-document rows in `patient_application_files`
  original_file_path: text,
  deidentified_file_path: text,
})

export type Patient = z.infer<typeof patientSchema>

export const patientListSchema = z.array(patientSchema)

// ------------------------------------------------------------ the form

/**
 * A controlled input is never null, so every optional field is a plain
 * string in the form and '' is normalised back to null on submit -- see
 * toPatientPayload in lib/api/resources.ts.
 */
const optionalText = (max = 128) => z.string().max(max, 'Too long')

/**
 * Deliberately permissive: the API stores phone numbers as opaque
 * STRINGs, so over-validating here would reject legitimate international
 * formats the backend accepts.
 */
const optionalPhone = z
  .string()
  .max(32, 'Too long')
  .regex(/^[+()\d\s-]*$/, 'Digits, spaces and + ( ) - only')

const optionalEmail = z.union([
  z.literal(''),
  z.string().email('Enter a valid email address'),
])

const optionalDate = z.union([
  z.literal(''),
  z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Use YYYY-MM-DD'),
])

/**
 * Mirrors app/schemas.py: everything is optional except the source
 * document and at least one identifier. The cross-field rule is applied
 * by `patientFormSchema` below; this object is kept unrefined so its
 * `.shape` still enumerates the fields.
 */
const patientFormFields = z.object({
  // provider / institution
  instcode: optionalText(64),
  pname: optionalText(),
  pemail: optionalEmail,
  phone1: optionalPhone,
  phone2: optionalPhone,
  wphone1: optionalPhone,
  wphone2: optionalPhone,
  street: optionalText(),
  street2: optionalText(),
  street3: optionalText(),
  city: optionalText(64),
  state: optionalText(64),
  zip: optionalText(16),
  country: optionalText(64),

  // patient
  fstname: optionalText(64),
  lstname: optionalText(64),
  ptemail: optionalEmail,
  ptphone: optionalPhone,
  ptphone2: optionalPhone,
  ptwphone: optionalPhone,
  ptwphone2: optionalPhone,
  ptstreet: optionalText(),
  ptstreet2: optionalText(),
  ptstreet3: optionalText(),
  ptcity: optionalText(64),
  ptstate: optionalText(64),
  ptzip: optionalText(16),
  ptcountry: optionalText(64),

  // dates
  dt_reg: optionalDate,
  dt_b: optionalDate,
  dt_d: optionalDate,

  // source documents. The original is the reason the record exists.
  original_file_path: z
    .string()
    .min(1, 'Original file path is required')
    .max(512, 'Too long'),
  deidentified_file_path: optionalText(512),
})

/**
 * The identity rule: a row nothing can be recognised by is not a record.
 * Any one of the three will do, because the systems these records are
 * ingested from disagree about which they populate.
 *
 * The message is reported against `fstname` so it lands under an input
 * rather than floating above the form -- it is the first of the three a
 * reader meets.
 */
export const PATIENT_IDENTIFIERS = ['fstname', 'lstname', 'ptemail'] as const

export const patientFormSchema = patientFormFields.superRefine((values, ctx) => {
  if (PATIENT_IDENTIFIERS.some((name) => values[name].trim() !== '')) return

  ctx.addIssue({
    code: 'custom',
    path: ['fstname'],
    message: 'Enter at least one of first name, last name or email',
  })
})

export type PatientFormValues = z.infer<typeof patientFormFields>

/** Every editable field, in the order the form declares them. */
export const PATIENT_FIELD_NAMES = Object.keys(patientFormFields.shape) as Array<
  keyof PatientFormValues
>

export const EMPTY_PATIENT_FORM: PatientFormValues = {
  instcode: '',
  pname: '',
  pemail: '',
  phone1: '',
  phone2: '',
  wphone1: '',
  wphone2: '',
  street: '',
  street2: '',
  street3: '',
  city: '',
  state: '',
  zip: '',
  country: '',
  fstname: '',
  lstname: '',
  ptemail: '',
  ptphone: '',
  ptphone2: '',
  ptwphone: '',
  ptwphone2: '',
  ptstreet: '',
  ptstreet2: '',
  ptstreet3: '',
  ptcity: '',
  ptstate: '',
  ptzip: '',
  ptcountry: '',
  dt_reg: '',
  dt_b: '',
  dt_d: '',
  original_file_path: '',
  deidentified_file_path: '',
}

/** A record from the API into the shape the form edits: null becomes ''. */
export function toPatientFormValues(patient: Patient): PatientFormValues {
  const values: PatientFormValues = { ...EMPTY_PATIENT_FORM }
  for (const name of PATIENT_FIELD_NAMES) {
    const value = patient[name]
    values[name] = typeof value === 'string' ? value : ''
  }
  return values
}

/**
 * Display name for headings, tables and confirmation dialogs.
 *
 * A patient may have no name at all -- only one of fstname/lstname/
 * ptemail is required -- so this falls back through the identifiers the
 * record is guaranteed to have one of, and never returns ''.
 */
export function patientName(patient: Patient): string {
  const name = [patient.fstname, patient.lstname].filter(Boolean).join(' ').trim()
  return name || patient.ptemail || 'Unnamed patient'
}
