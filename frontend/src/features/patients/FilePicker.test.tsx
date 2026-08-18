import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FilePicker } from './FilePicker'

const toastError = vi.fn()
const toastWarning = vi.fn()

vi.mock('sonner', () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    warning: (...args: unknown[]) => toastWarning(...args),
  },
}))

beforeEach(() => {
  toastError.mockClear()
  toastWarning.mockClear()
})

function pdfFile(name: string): File {
  const bytes = [0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34] // '%PDF-1.4'
  return new File([new Uint8Array(bytes)], name)
}

function textFile(name: string): File {
  return new File([new Uint8Array([1, 2, 3])], name)
}

function renderPicker(onFilesChange = vi.fn()) {
  render(<FilePicker files={[]} onFilesChange={onFilesChange} />)
  return onFilesChange
}

describe('FilePicker', () => {
  it('choosing files: keeps a supported pick and raises no error', async () => {
    const onFilesChange = renderPicker()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Choose files' }))
    const pdf = pdfFile('scan.pdf')
    await user.upload(screen.getByLabelText('File input'), [pdf])

    expect(onFilesChange).toHaveBeenCalledWith([pdf])
    expect(toastError).not.toHaveBeenCalled()
  })

  it('choosing files: an unsupported file is rejected with an error, not silently added', async () => {
    const onFilesChange = renderPicker()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Choose files' }))
    const txt = textFile('notes.txt')
    await user.upload(screen.getByLabelText('File input'), [txt])

    expect(onFilesChange).toHaveBeenCalledWith([])
    expect(toastError).toHaveBeenCalledTimes(1)
    expect(toastError.mock.calls[0]?.[0]).toMatch(/notes\.txt.*not a supported file type/)
  })

  it('choosing files: keeps the supported ones and errors on the rest of a mixed pick', async () => {
    const onFilesChange = renderPicker()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Choose files' }))
    const pdf = pdfFile('scan.pdf')
    const txt = textFile('notes.txt')
    await user.upload(screen.getByLabelText('File input'), [pdf, txt])

    expect(onFilesChange).toHaveBeenCalledWith([pdf])
    expect(toastError).toHaveBeenCalledTimes(1)
  })

  it('choosing a folder: unsupported files are dropped quietly, with only a warning', async () => {
    const onFilesChange = renderPicker()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Choose folder' }))
    const pdf = pdfFile('scan.pdf')
    const txt = textFile('notes.txt')
    await user.upload(screen.getByLabelText('File input'), [pdf, txt])

    expect(onFilesChange).toHaveBeenCalledWith([pdf])
    expect(toastError).not.toHaveBeenCalled()
    expect(toastWarning).toHaveBeenCalledTimes(1)
    expect(toastWarning.mock.calls[0]?.[0]).toMatch(/Skipped 1 unsupported file/)
  })

  it('choosing a folder: an all-unsupported folder is reported as an error, not left silent', async () => {
    const onFilesChange = renderPicker()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Choose folder' }))
    await user.upload(screen.getByLabelText('File input'), [textFile('a.txt'), textFile('b.txt')])

    expect(onFilesChange).toHaveBeenCalledWith([])
    expect(toastError).toHaveBeenCalledTimes(1)
    expect(toastWarning).not.toHaveBeenCalled()
  })
})
