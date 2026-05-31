import { describe, expect, it } from 'vitest'
import {
  fingerprintLocalFiles,
  fingerprintPersistedMaterials,
  fingerprintWizardMaterials,
  materialsWizardInputsChanged,
} from './superAgentMaterialsFingerprint'

describe('superAgentMaterialsFingerprint', () => {
  it('detects persisted material list changes', () => {
    const before = fingerprintPersistedMaterials([{ name: 'a.pdf', file_size: 100 }])
    const after = fingerprintPersistedMaterials([{ name: 'b.pdf', file_size: 200 }])
    expect(before).not.toBe(after)
  })

  it('detects local file additions', () => {
    const baseline = fingerprintWizardMaterials([{ name: 'saved.md' }], [])
    const changed = fingerprintWizardMaterials(
      [{ name: 'saved.md' }],
      [{ file: new File(['x'], 'new.txt', { type: 'text/plain' }) }],
    )
    expect(materialsWizardInputsChanged(baseline, [{ name: 'saved.md' }], [])).toBe(false)
    expect(
      materialsWizardInputsChanged(baseline, [{ name: 'saved.md' }], [
        { file: new File(['x'], 'new.txt', { type: 'text/plain' }) },
      ]),
    ).toBe(true)
    expect(baseline).not.toBe(changed)
  })

  it('ignores order of persisted materials', () => {
    const a = fingerprintPersistedMaterials([
      { name: 'b.pdf', file_size: 2 },
      { name: 'a.pdf', file_size: 1 },
    ])
    const b = fingerprintPersistedMaterials([
      { name: 'a.pdf', file_size: 1 },
      { name: 'b.pdf', file_size: 2 },
    ])
    expect(a).toBe(b)
  })

  it('tracks local files by name and size', () => {
    const fp = fingerprintLocalFiles([
      { file: new File(['ab'], 'doc.txt', { type: 'text/plain' }) },
    ])
    expect(fp).toContain('doc.txt')
  })
})
