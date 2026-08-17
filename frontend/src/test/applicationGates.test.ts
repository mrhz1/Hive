/**
 * The rules that decide what the wizard will let somebody do.
 *
 * Each of these is a "no" the UI gives on a button, and each one used to
 * be spelled out inline at the call site. They are here because getting
 * one wrong is silent -- the button simply stays enabled, and something
 * that should not have gone for review does.
 */
import { describe, expect, it } from 'vitest'
import { rejectedCount, undecidedCount } from '@/schemas/applicationFile'
import { canDelete, canReject, isReadOnly } from '@/schemas/patientApplication'

function files(...statuses: string[]) {
  return statuses.map((review_status) => ({ review_status }))
}

describe('counting what still stands in the way', () => {
  it('counts the documents nobody has decided about', () => {
    expect(undecidedCount(files('pending', 'approved', 'rejected'))).toBe(1)
  })

  it('counts the documents that were turned down', () => {
    expect(rejectedCount(files('rejected', 'approved', 'rejected'))).toBe(2)
  })

  it('finds nothing in the way of an empty application', () => {
    expect(undecidedCount([])).toBe(0)
    expect(rejectedCount([])).toBe(0)
  })
})

describe('rejecting an application', () => {
  it('is still on offer once it has already been rejected', () => {
    // The first problem gets fixed, the next one surfaces, and it has to
    // be possible to say so -- with its own reason.
    expect(canReject('rejected')).toBe(true)
  })

  it('is not offered on one that has gone for review', () => {
    expect(canReject('submitted')).toBe(false)
  })

  it('is not offered on one that has been deleted', () => {
    expect(canReject('deleted')).toBe(false)
  })

  it('is offered on a draft and on an approved application', () => {
    expect(canReject('draft')).toBe(true)
    expect(canReject('approved')).toBe(true)
  })
})

describe('a submitted application is a record, not a form', () => {
  it('is read-only', () => {
    expect(isReadOnly('submitted')).toBe(true)
  })

  it('leaves a draft and a rejected application editable', () => {
    expect(isReadOnly('draft')).toBe(false)
    expect(isReadOnly('rejected')).toBe(false)
  })

  it('is not read-only before there is an application at all', () => {
    expect(isReadOnly(undefined)).toBe(false)
  })

  it('cannot be deleted either', () => {
    expect(canDelete('submitted')).toBe(false)
  })
})
