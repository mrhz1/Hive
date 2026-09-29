import { describe, expect, it } from 'vitest'
import { byFolder, intakeHaystack, refusalReport, type IntakeFile } from '@/schemas/intake'

function file(overrides: Partial<IntakeFile>): IntakeFile {
  return {
    id: 'f1',
    batch_id: 'b1',
    source_path: '/drop/loose/REPORT_final.pdf',
    relative_path: 'loose/REPORT_final.pdf',
    file_name: 'REPORT_final.pdf',
    file_extension: 'pdf',
    file_size: 10,
    status: 'skipped',
    reason: 'no patient code',
    detail: 'no code in the path or the file name',
    ...overrides,
  }
}

describe('refusalReport', () => {
  it('puts one file per line, full path first', () => {
    const report = refusalReport([
      file({}),
      file({
        source_path: '/drop/loose/IM000001',
        reason: 'unsupported format',
        detail: "'no extension'",
      }),
    ])

    expect(report.split('\n')).toEqual([
      '/drop/loose/REPORT_final.pdf\tno patient code\tno code in the path or the file name',
      "/drop/loose/IM000001\tunsupported format\t'no extension'",
    ])
  })

  it('falls back to the status when there is no reason', () => {
    expect(refusalReport([file({ reason: null, detail: null, status: 'failed' })])).toBe(
      '/drop/loose/REPORT_final.pdf\tfailed'
    )
  })
})

describe('intakeHaystack', () => {
  it('finds a conflict by either of its codes', () => {
    const conflict = file({ path_code: 'BB0042', name_code: 'BB9999' })

    expect(intakeHaystack(conflict)).toContain('bb0042')
    expect(intakeHaystack(conflict)).toContain('bb9999')
  })
})

describe('byFolder', () => {
  it('groups by the folder under the code, so a whole folder can be taken', () => {
    const groups = byFolder([
      file({ id: 'a', patient_code: 'AA1234', relative_path: 'A/B/C/AA1234/image.pdf' }),
      file({ id: 'b', patient_code: 'AA1234', relative_path: 'A/B/C/AA1234/ct/s1.dcm' }),
      file({ id: 'c', patient_code: 'AA1234', relative_path: 'A/B/C/AA1234/ct/s2.dcm' }),
    ])

    expect(groups.map(([folder, rows]) => [folder, rows.map((r) => r.id)])).toEqual([
      ['AA1234', ['a']],
      ['AA1234/ct', ['b', 'c']],
    ])
  })

  it('falls back to the path when the code was only in the file name', () => {
    const groups = byFolder([
      file({ patient_code: 'AA1234', relative_path: 'loose/AA1234_x.pdf' }),
    ])

    expect(groups[0]?.[0]).toBe('loose')
  })
})
