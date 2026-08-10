import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Patient } from '@/schemas/patient'

const useList = vi.fn()

vi.mock('@/hooks/useResources', () => ({
  patientHooks: { useList: () => useList() },
}))

const { ExistingPatientPicker } = await import('./ExistingPatientPicker')

function patient(overrides: Partial<Patient>): Patient {
  return {
    id: 'A7K2P9',
    fstname: 'Jane',
    lstname: 'Doe',
    ptemail: 'jane@example.com',
    ptphone: '555-0100',
    ...overrides,
  } as Patient
}

const PATIENTS = [
  patient({ id: 'A7K2P9', fstname: 'Jane', lstname: 'Doe', ptemail: 'jane@example.com' }),
  patient({ id: 'B3M8Q1', fstname: 'John', lstname: 'Smith', ptemail: 'john@example.com' }),
  patient({ id: 'C5N2R7', fstname: 'Ada', lstname: 'Byron', ptemail: 'ada@example.com' }),
]

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function renderPicker(onSelect = vi.fn()) {
  render(<ExistingPatientPicker onSelect={onSelect} />, { wrapper })
  return onSelect
}

describe('ExistingPatientPicker', () => {
  beforeEach(() => {
    useList.mockReturnValue({ data: PATIENTS, isLoading: false, error: null })
  })

  it('lists every patient on file', () => {
    renderPicker()

    const list = screen.getByRole('list', { name: 'Patients' })
    expect(within(list).getAllByRole('button')).toHaveLength(3)
  })

  it('shows the patient id, which is what people quote', () => {
    renderPicker()

    expect(screen.getByText('A7K2P9')).toBeInTheDocument()
  })

  it('filters by name', async () => {
    renderPicker()

    await userEvent.type(screen.getByLabelText('Find a patient'), 'ada')

    const list = screen.getByRole('list', { name: 'Patients' })
    expect(within(list).getAllByRole('button')).toHaveLength(1)
    expect(within(list).getByText('Ada Byron')).toBeInTheDocument()
  })

  it('filters by patient id', async () => {
    renderPicker()

    await userEvent.type(screen.getByLabelText('Find a patient'), 'B3M8Q1')

    const list = screen.getByRole('list', { name: 'Patients' })
    expect(within(list).getAllByRole('button')).toHaveLength(1)
    expect(within(list).getByText('John Smith')).toBeInTheDocument()
  })

  it('filters by email', async () => {
    renderPicker()

    await userEvent.type(screen.getByLabelText('Find a patient'), 'john@')

    const list = screen.getByRole('list', { name: 'Patients' })
    expect(within(list).getAllByRole('button')).toHaveLength(1)
  })

  it('says so when nothing matches', async () => {
    renderPicker()

    await userEvent.type(screen.getByLabelText('Find a patient'), 'zzzz')

    expect(screen.getByText(/No patient matches/)).toBeInTheDocument()
  })

  it('cannot continue until a patient is picked', async () => {
    const onSelect = renderPicker()

    expect(screen.getByRole('button', { name: 'Select a patient' })).toBeDisabled()
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('hands the chosen patient back', async () => {
    const onSelect = renderPicker()

    await userEvent.click(screen.getByText('John Smith'))
    await userEvent.click(screen.getByRole('button', { name: /Continue with John Smith/ }))

    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0]?.[0]?.id).toBe('B3M8Q1')
  })

  it('points at the new-patient route when there is nobody on file', () => {
    useList.mockReturnValue({ data: [], isLoading: false, error: null })
    renderPicker()

    expect(screen.getByText(/no patients on file/i)).toBeInTheDocument()
  })

  it('degrades to a message rather than an empty list on error', () => {
    useList.mockReturnValue({ data: undefined, isLoading: false, error: new Error('nope') })
    renderPicker()

    expect(screen.getByText(/Could not load patients/)).toBeInTheDocument()
  })
})
