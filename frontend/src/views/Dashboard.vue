<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">按当前身份的可见范围汇总，跨单位数据只显示有无、不显示条数。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="saveSnapshot">保存当前快照</button>
      </div>
    </header>

    <p v-if="scopeText" class="scope-line">当前可见范围：{{ scopeText }} · 汇总口径 {{ criteriaVersion }}</p>

    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>数据范围</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.label }}</td>
          <template v-if="row.scope === 'cross'">
            <td><span class="tag cross">跨单位</span></td>
            <td colspan="3" class="muted-cell">有数据，条数不可见</td>
          </template>
          <template v-else>
            <td><span class="tag">本单位</span></td>
            <td>{{ row.created }}</td>
            <td>{{ row.pending }}</td>
            <td>{{ row.abnormal }}</td>
          </template>
        </tr>
        <tr v-if="!moduleRows.length">
          <td colspan="5" class="empty-state">概览数据未加载</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">历史快照</h3>
    <p class="page-desc">快照按保存时的可见范围与口径留存；汇总口径调整后按新口径重算，已落库的旧快照不回头改写。</p>
    <table class="data-table">
      <thead>
        <tr><th>保存时间</th><th>操作人</th><th>可见范围</th><th>口径版本</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="snap in snapshots" :key="snap.id">
          <td>{{ snap.created_at }}</td>
          <td>{{ snap.operator }}（{{ snap.role_label }}）</td>
          <td>{{ snap.unit_label }}</td>
          <td>{{ snap.criteria_version }}</td>
          <td>{{ cardValue(snap, '今日新增') }}</td>
          <td>{{ cardValue(snap, '待处理') }}</td>
          <td>{{ cardValue(snap, '异常量') }}</td>
        </tr>
        <tr v-if="!snapshots.length">
          <td colspan="7" class="empty-state">暂无快照，可点击右上角「保存当前快照」留存一份</td>
        </tr>
      </tbody>
    </table>

    <template v-if="store.isAdmin">
      <h3 class="section-title">越权访问记录</h3>
      <p class="page-desc">越权访问与跨单位改动一律拒绝并记在这里，仅矿级管理员可见。</p>
      <table class="data-table">
        <thead>
          <tr><th>时间</th><th>操作人</th><th>角色</th><th>单位</th><th>动作</th><th>对象</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="log in auditLogs" :key="log.id">
            <td>{{ log.ts }}</td>
            <td>{{ log.operator }}</td>
            <td>{{ log.role_label }}</td>
            <td>{{ log.unit_label }}</td>
            <td>{{ log.action }}</td>
            <td>{{ log.target }}</td>
            <td>{{ log.detail }}</td>
          </tr>
          <tr v-if="!auditLogs.length">
            <td colspan="7" class="empty-state">暂无越权访问记录</td>
          </tr>
        </tbody>
      </table>
    </template>

    <footer class="page-foot">
      <span v-if="noticeMessage" class="muted-cell">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { fetchJson, postJson } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Card = { label: string; value: number }
type ModuleRow = {
  name: string
  label: string
  scope: 'own' | 'cross'
  has_data: boolean
  created: number | null
  pending: number | null
  abnormal: number | null
}
type Overview = {
  cards: Card[]
  modules: ModuleRow[]
  criteria_version: string
  scope: { role_label: string; unit_label: string; whole_mine: boolean }
}
type Snapshot = {
  id: number
  created_at: string
  operator: string
  role_label: string
  unit_label: string
  criteria_version: string
  cards: Card[]
}
type AuditLog = {
  id: number
  ts: string
  operator: string
  role_label: string
  unit_label: string
  action: string
  target: string
  detail: string
}

const store = useSessionStore()

const cards = ref<Card[]>([])
const moduleRows = ref<ModuleRow[]>([])
const criteriaVersion = ref('')
const scopeText = ref('')
const snapshots = ref<Snapshot[]>([])
const auditLogs = ref<AuditLog[]>([])
const errorMessage = ref('')
const noticeMessage = ref('')

const identityKey = computed(() => `${store.role}:${store.unitId}`)

function cardValue(snap: Snapshot, label: string): number | string {
  return snap.cards.find((card) => card.label === label)?.value ?? '—'
}

async function loadOverview() {
  const payload = await fetchJson<Overview>('/api/overview')
  cards.value = payload.cards
  moduleRows.value = payload.modules
  criteriaVersion.value = payload.criteria_version
  scopeText.value = `${payload.scope.unit_label}（${payload.scope.role_label}）`
}

async function loadSnapshots() {
  const payload = await fetchJson<{ items: Snapshot[] }>('/api/overview/snapshots')
  snapshots.value = payload.items
}

async function loadAuditLogs() {
  if (!store.isAdmin) {
    auditLogs.value = []
    return
  }
  const payload = await fetchJson<{ items: AuditLog[] }>('/api/audit/logs')
  auditLogs.value = payload.items
}

async function reload() {
  errorMessage.value = ''
  try {
    await Promise.all([loadOverview(), loadSnapshots(), loadAuditLogs()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '运营概览加载失败'
  }
}

async function saveSnapshot() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    await postJson('/api/overview/snapshots')
    noticeMessage.value = '快照已按当前可见范围与口径落库'
    await loadSnapshots()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照保存失败'
  }
}

watch(identityKey, () => {
  noticeMessage.value = ''
  void reload()
})

onMounted(reload)
</script>

<style scoped>
.scope-line { color: var(--muted); font-size: 13px; margin: 0 0 12px; }
.section-title { font-size: 15px; margin: 20px 0 4px; }
.tag { display: inline-block; border: 1px solid var(--border); border-radius: 10px; padding: 1px 8px; font-size: 12px; color: var(--muted); }
.tag.cross { color: #b42318; border-color: #f0c4bd; background: #fdf3f2; }
.muted-cell { color: var(--muted); font-size: 13px; }
</style>
