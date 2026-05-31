type RecordLike = Record<string, unknown>

function pushUnique(ids: string[], value: unknown) {
  const id = String(value || '').trim()
  if (id && !ids.includes(id)) ids.push(id)
}

export function collectStringIds(record: RecordLike, keys: readonly string[]): string[] {
  const ids: string[] = []
  for (const key of keys) {
    const raw = record[key]
    if (Array.isArray(raw)) {
      for (const value of raw) pushUnique(ids, value)
      continue
    }
    pushUnique(ids, raw)
  }
  return ids
}

export function collectRelatedEvidenceIds(item: RecordLike): string[] {
  return collectStringIds(item, [
    'related_evidence_ids',
    'evidence_ids',
    'source_evidence_ids',
    'linked_evidence_ids',
    'evidence_id',
  ])
}

export function collectRelatedRidIds(item: RecordLike): string[] {
  return collectStringIds(item, [
    'related_rid_ids',
    'rid_ids',
    'related_rid_id',
    'linked_rid_id',
    'linked_rid_ids',
  ])
}

export function extractEvidenceRidId(item: RecordLike): string {
  const ridIds = collectStringIds(item, [
    'related_rid_ids',
    'rid_ids',
    'related_rid_id',
    'rid_id',
    'review_item_id',
    'review_item_ids',
    'linked_rid_id',
  ])
  if (ridIds.length) return ridIds[0]
  return String(item.rid || '').trim()
}

export function extractRidContext(item: RecordLike): {
  ruleId: string
  unitKey: string
  sectionId: string
  reviewItemId: string
} {
  return {
    ruleId: String(item.source_rule_id || item.rule_id || '').trim(),
    unitKey: String(item.source_unit_key || item.unit_key || item.unit_id || '').trim(),
    sectionId: String(item.source_section_id || item.section_id || '').trim(),
    reviewItemId: String(item.review_item_id || item.review_item || '').trim(),
  }
}

export function extractRuleLinkTargets(rule: RecordLike): {
  evidenceIds: string[]
  ridIds: string[]
} {
  return {
    evidenceIds: collectRelatedEvidenceIds(rule),
    ridIds: collectStringIds(rule, [
      'related_rid_ids',
      'rid_ids',
      'related_rid_id',
      'linked_rid_id',
      'linked_rid_ids',
      'rid_id',
    ]),
  }
}
