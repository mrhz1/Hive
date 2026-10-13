import { z } from 'zod'

// Mirrors app/lockdown.py and app/incidents.py.

export const LEVELS = ['low', 'high', 'critical'] as const
export type Level = (typeof LEVELS)[number]

export const lockdownSchema = z.object({
  locked: z.boolean(),
  reason: z.string().nullable().optional(),
  level: z.string().nullable().optional(),
  locked_at: z.string().nullable().optional(),
  locked_by: z.string().nullable().optional(),
})

export type Lockdown = z.infer<typeof lockdownSchema>

export const incidentSchema = z.object({
  id: z.string(),
  title: z.string(),
  level: z.string(),
  status: z.string(),
  detected_at: z.string(),
  description: z.string().nullable().optional(),
  data_affected: z.string().nullable().optional(),
  risk: z.string().nullable().optional(),
  containment: z.string().nullable().optional(),
  affected_parties: z.string().nullable().optional(),
  preliminary_sent_at: z.string().nullable().optional(),
  full_sent_at: z.string().nullable().optional(),
  preliminary_due: z.string().nullable().optional(),
  full_due: z.string().nullable().optional(),
  closed_at: z.string().nullable().optional(),
})

export type Incident = z.infer<typeof incidentSchema>

export const incidentListSchema = z.array(incidentSchema)

export type IncidentPayload = {
  title?: string
  level?: Level
  detected_at?: string
  description?: string | null
  data_affected?: string | null
  risk?: string | null
  containment?: string | null
  affected_parties?: string | null
}

export function levelTone(level: string): 'neutral' | 'warning' | 'danger' {
  if (level === 'critical') return 'danger'
  if (level === 'high') return 'warning'
  return 'neutral'
}

/** 'sent 2026-10-02 08:10', 'OVERDUE', or 'due in 5 h'. */
export function deadline(
  due: string | null | undefined,
  sent: string | null | undefined,
  now = Date.now()
): { text: string; tone: 'success' | 'danger' | 'warning' | 'neutral' } {
  if (sent)
    return { text: `sent ${sent.slice(0, 16).replace('T', ' ')}`, tone: 'success' }
  if (!due) return { text: '—', tone: 'neutral' }
  const hours = Math.floor((Date.parse(due) - now) / 3_600_000)
  if (hours < 0)
    return { text: `OVERDUE (due ${due.slice(0, 16).replace('T', ' ')})`, tone: 'danger' }
  return { text: `due in ${hours} h`, tone: hours <= 6 ? 'warning' : 'neutral' }
}
