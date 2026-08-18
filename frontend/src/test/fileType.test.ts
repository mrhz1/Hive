import { describe, expect, it } from 'vitest'
import { isSupportedUpload, partitionBySupport } from '@/lib/fileType'

function file(name: string, bytes: number[] = [], type = ''): File {
  return new File([new Uint8Array(bytes)], name, { type })
}

function dicomBytes(): number[] {
  const preamble = new Array(128).fill(0)
  const magic = [0x44, 0x49, 0x43, 0x4d] // 'DICM'
  return [...preamble, ...magic, 0, 0]
}

function pdfBytes(): number[] {
  return [0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34] // '%PDF-1.4'
}

describe('isSupportedUpload', () => {
  it('accepts known extensions regardless of content', async () => {
    await expect(isSupportedUpload(file('scan.pdf'))).resolves.toBe(true)
    await expect(isSupportedUpload(file('scan.DCM'))).resolves.toBe(true)
    await expect(isSupportedUpload(file('image.dicom'))).resolves.toBe(true)
    await expect(isSupportedUpload(file('report.doc'))).resolves.toBe(true)
    await expect(isSupportedUpload(file('report.docx'))).resolves.toBe(true)
  })

  it('rejects an unrelated extension whose bytes are not one of the known formats', async () => {
    await expect(isSupportedUpload(file('notes.txt', [1, 2, 3]))).resolves.toBe(false)
    await expect(isSupportedUpload(file('script.py', [1, 2, 3]))).resolves.toBe(false)
  })

  it('sniffs a DICOM off a PACS that carries no extension at all', async () => {
    await expect(isSupportedUpload(file('IM000001', dicomBytes()))).resolves.toBe(true)
  })

  it('sniffs a PDF whose extension was stripped or renamed', async () => {
    await expect(isSupportedUpload(file('document', pdfBytes()))).resolves.toBe(true)
    await expect(isSupportedUpload(file('document.bin', pdfBytes()))).resolves.toBe(true)
  })

  it('rejects an empty or unreadable file', async () => {
    await expect(isSupportedUpload(file('mystery'))).resolves.toBe(false)
  })
})

describe('partitionBySupport', () => {
  it('splits a mixed batch and keeps each file in exactly one side', async () => {
    const pdf = file('scan.pdf')
    const doc = file('report.docx')
    const txt = file('notes.txt', [1, 2, 3])

    const { supported, unsupported } = await partitionBySupport([pdf, txt, doc])

    expect(supported).toEqual([pdf, doc])
    expect(unsupported).toEqual([txt])
  })

  it('returns empty arrays for an empty batch', async () => {
    const { supported, unsupported } = await partitionBySupport([])
    expect(supported).toEqual([])
    expect(unsupported).toEqual([])
  })
})
