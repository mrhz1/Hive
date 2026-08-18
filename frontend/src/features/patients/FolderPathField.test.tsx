import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FolderPathField } from './FolderPathField'

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

function renderField(onSelect = vi.fn()) {
  render(<FolderPathField label="Source folder" value="" files={[]} onSelect={onSelect} />)
  return onSelect
}

describe('FolderPathField', () => {
  it('choosing files: an unsupported file is rejected with an error', async () => {
    const onSelect = renderField()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Choose files' }))
    await user.upload(screen.getByLabelText('Source folder input'), [textFile('notes.txt')])

    // The picked file is rejected -- the path field still fills in from
    // the raw pick, same as folderPathFromFiles does for any single file.
    expect(onSelect).toHaveBeenCalledWith('notes.txt', [])
    expect(toastError).toHaveBeenCalledTimes(1)
  })

  it('choosing a folder: unsupported files are dropped quietly, and the folder name still fills the path', async () => {
    const onSelect = renderField()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Choose folder' }))
    const pdf = pdfFile('scan.pdf')
    Object.defineProperty(pdf, 'webkitRelativePath', { value: 'samples/scan.pdf' })
    const txt = textFile('notes.txt')
    Object.defineProperty(txt, 'webkitRelativePath', { value: 'samples/notes.txt' })

    await user.upload(screen.getByLabelText('Source folder input'), [pdf, txt])

    expect(onSelect).toHaveBeenCalledWith('samples', [pdf])
    expect(toastError).not.toHaveBeenCalled()
    expect(toastWarning).toHaveBeenCalledTimes(1)
  })
})
