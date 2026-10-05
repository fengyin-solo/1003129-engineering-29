import { defineStore } from 'pinia'

export type Operator = {
  id: string
  name: string
  role: string
  roleLabel: string
  unit: string
}

/** 演示用操作者目录，与后端 app/users.py 保持一致；真实项目里身份来自登录态。 */
export const OPERATORS: Operator[] = [
  { id: 'admin', name: '值班管理员', role: 'admin', roleLabel: '矿级管理员', unit: '矿调度中心' },
  { id: 'leader1', name: '综采一队班组长', role: 'teamlead', roleLabel: '班组长', unit: '综采一队' },
  { id: 'leader2', name: '综采二队班组长', role: 'teamlead', roleLabel: '班组长', unit: '综采二队' },
  { id: 'contractor1', name: '外委维修队负责人', role: 'contractor', roleLabel: '外委单位', unit: '外委维修队' },
]

const STORAGE_KEY = 'mine-operator-id'

export const useSessionStore = defineStore('session', {
  state: () => ({
    operatorId: localStorage.getItem(STORAGE_KEY) ?? 'admin',
    shiftLabel: '白班 08:00-20:00',
    scope: '矿山安全监测管理平台',
  }),
  getters: {
    operator: (state) => OPERATORS.find((item) => item.id === state.operatorId) ?? OPERATORS[0],
    canOperate: (state) => state.operatorId.length > 0,
  },
  actions: {
    setOperator(id: string) {
      this.operatorId = id
      localStorage.setItem(STORAGE_KEY, id)
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
