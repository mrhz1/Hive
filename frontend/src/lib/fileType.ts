import { canDeidentify } from '@/schemas/applicationFile'

export const SUPPORTED_FORMATS_LABEL = 'DICOM, PDF, or Word'

const DICOM_PREAMBLE_BYTES = 128
const DICOM_MAGIC = 'DICM'
const PDF_MAGIC = '%PDF-'
const OLE_MAGIC = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]
const ZIP_MAGIC = [0x50, 0x4b, 0x03, 0x04]
const SNIFF_BYTES = 4096

function nameExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot === -1 ? '' : name.slice(dot + 1).toLowerCase()
}

function startsWithAscii(bytes: Uint8Array, ascii: string, offset = 0): boolean {
  if (bytes.length < offset + ascii.length) return false
  for (let i = 0; i < ascii.length; i += 1) {
    if (bytes[offset + i] !== ascii.charCodeAt(i)) return false
  }
  return true
}

function startsWithBytes(bytes: Uint8Array, magic: number[]): boolean {
  if (bytes.length < magic.length) return false
  for (let i = 0; i < magic.length; i += 1) {
    if (bytes[i] !== magic[i]) return false
  }
  return true
}

function sniffExtension(head: Uint8Array): string | null {
  if (head.length === 0) return null

  if (
    startsWithAscii(head, DICOM_MAGIC, DICOM_PREAMBLE_BYTES) ||
    startsWithAscii(head, DICOM_MAGIC)
  ) {
    return 'dcm'
  }

  if (startsWithAscii(head, PDF_MAGIC)) return 'pdf'

  if (startsWithBytes(head, OLE_MAGIC)) return 'doc'

  if (startsWithBytes(head, ZIP_MAGIC)) {
    const text = new TextDecoder('latin1').decode(head)
    if (text.includes('word/')) return 'docx'
  }

  return null
}

async function readHead(file: File, bytes = SNIFF_BYTES): Promise<Uint8Array> {
  const buffer = await file.slice(0, bytes).arrayBuffer()
  return new Uint8Array(buffer)
}

export async function isSupportedUpload(file: File): Promise<boolean> {
  if (canDeidentify(nameExtension(file.name))) return true
  return sniffExtension(await readHead(file)) !== null
}

export async function partitionBySupport(
  files: File[]
): Promise<{ supported: File[]; unsupported: File[] }> {
  const flags = await Promise.all(files.map(isSupportedUpload))
  const supported: File[] = []
  const unsupported: File[] = []
  files.forEach((file, index) => {
    ;(flags[index] ? supported : unsupported).push(file)
  })
  return { supported, unsupported }
}
