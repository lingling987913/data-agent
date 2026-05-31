import type { SuperAgentMaterialInput } from '@/features/super-agent/types'
import { uploadSuperAgentMaterials } from '@/features/super-agent/api'

/** 将浏览器 File 列表上传到服务端，并转为 Super Agent 可引用的材料 payload。 */
export async function filesToMaterials(files: File[]): Promise<SuperAgentMaterialInput[]> {
  const validFiles = files.filter((file) => !file.name.startsWith('~$'))
  if (!validFiles.length) return []
  const uploaded = await uploadSuperAgentMaterials(validFiles)
  return uploaded.materials.map((material) => ({
    ...material,
    content: '',
    content_base64: '',
    parser_type: material.parser_type || 'auto',
  }))
}
