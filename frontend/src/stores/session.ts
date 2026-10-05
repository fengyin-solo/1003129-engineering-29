import { defineStore } from 'pinia'

/** 身份预设：演示不同角色与矿区归属下的可见范围。 */
export type IdentityPreset = {
  label: string
  operator: string
  role: 'admin' | 'team_lead' | 'contractor'
  unitId: string
}

export const IDENTITY_PRESETS: IdentityPreset[] = [
  { label: '矿级管理员 · 全矿', operator: '值班管理员', role: 'admin', unitId: 'mine-1' },
  { label: '班组长 · 一采区', operator: '一采区班组长', role: 'team_lead', unitId: 'mine-1' },
  { label: '班组长 · 二采区', operator: '二采区班组长', role: 'team_lead', unitId: 'mine-2' },
  { label: '外委单位 · 外委一队', operator: '外委一队负责人', role: 'contractor', unitId: 'contractor-1' },
]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    role: 'admin' as IdentityPreset['role'],
    unitId: 'mine-1',
    shiftLabel: '白班 08:00-20:00',
    scope: '矿山安全监测管理平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isAdmin: (state) => state.role === 'admin',
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setIdentity(preset: IdentityPreset) {
      this.operator = preset.operator
      this.role = preset.role
      this.unitId = preset.unitId
    },
  },
})
