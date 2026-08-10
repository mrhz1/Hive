import { z } from 'zod'
import { idSchema } from './common'


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

  original_file_path: text,
  deidentified_file_path: text,
})

export type Patient = z.infer<typeof patientSchema>

export const patientListSchema = z.array(patientSchema)

// ------------------------------------------------------------ the form

const optionalText = (max = 128) => z.string().max(max, 'Too long')

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

export function patientName(patient: Patient): string {
  const name = [patient.fstname, patient.lstname].filter(Boolean).join(' ').trim()
  return name || patient.ptemail || 'Unnamed patient'
}
