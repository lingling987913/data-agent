import type { SuperAgentMaterialInput } from '@/features/super-agent/types'

export type LocalMaterialFile = { file: File }

function materialKey(material: SuperAgentMaterialInput): [string, number, string, string, string, string] {
  return [
    String(material.name || '').trim(),
    Number(material.file_size || 0),
    String(material.file_id || '').trim(),
    String(material.upload_id || '').trim(),
    String(material.file_path || '').trim(),
    String(material.role || '').trim(),
  ]
}

function localFileKey(item: LocalMaterialFile): [string, number] {
  return [String(item.file.name || '').trim(), Number(item.file.size || 0)]
}

export function fingerprintPersistedMaterials(materials: SuperAgentMaterialInput[]): string {
  const keys = materials.map(materialKey).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))
  return JSON.stringify(keys)
}

export function fingerprintLocalFiles(files: LocalMaterialFile[]): string {
  const keys = files.map(localFileKey).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))
  return JSON.stringify(keys)
}

export function fingerprintWizardMaterials(
  persisted: SuperAgentMaterialInput[],
  localFiles: LocalMaterialFile[],
): string {
  return `${fingerprintPersistedMaterials(persisted)}|${fingerprintLocalFiles(localFiles)}`
}

export function materialsWizardInputsChanged(
  baseline: string,
  persisted: SuperAgentMaterialInput[],
  localFiles: LocalMaterialFile[],
): boolean {
  return baseline !== fingerprintWizardMaterials(persisted, localFiles)
}
