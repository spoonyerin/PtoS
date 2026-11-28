export type FamilyMember = { id: string; name: string; relation: string; status: 'connected' | 'pending' }
export type FamilyModel = { members: FamilyMember[]; autoAlert: boolean; recipientId: string | null }
export function createFamilyModel(connected = true): FamilyModel {
  return { members: connected ? [
    { id: 'daughter', name: '우리딸♥', relation: '자식', status: 'connected' },
    { id: 'sibling', name: '동생', relation: '형제', status: 'pending' },
  ] : [], autoAlert: false, recipientId: connected ? 'daughter' : null }
}
