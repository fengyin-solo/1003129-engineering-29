<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">
          当前身份：{{ operatorText }}。概览按角色与单位归属过滤，本单位名下模块显示条数，
          跨单位数据只显示有无；汇总口径与各模块列表一致（{{ caliberText }}）。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="saveSnapshot">保存概览快照</button>
      </div>
    </header>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <h3 class="section-title">本单位名下模块</h3>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ moduleLabel(row.name) }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
        <tr v-if="!moduleRows.length">
          <td colspan="4" class="empty-state">本单位名下暂无模块数据</td>
        </tr>
      </tbody>
    </table>

    <template v-if="crossUnits.length">
      <h3 class="section-title">跨单位数据</h3>
      <p class="section-desc">跨单位数据不显示条数，只显示有无。</p>
      <table class="data-table">
        <thead>
          <tr><th>业务模块</th><th>有无数据</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in crossUnits" :key="row.name">
            <td>{{ moduleLabel(row.name) }}</td>
            <td :class="row.hasData ? 'presence-yes' : 'presence-no'">{{ row.hasData ? '有数据' : '无数据' }}</td>
          </tr>
        </tbody>
      </table>
    </template>

    <h3 class="section-title">概览快照</h3>
    <p class="section-desc">
      快照按落库时的汇总口径与可见范围保留，口径调整后新快照按新口径重算，已落库的旧快照不回头改写。
    </p>
    <table class="data-table">
      <thead>
        <tr>
          <th>编号</th><th>保存时间</th><th>标签</th><th>口径</th><th>可见范围</th>
          <th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="snap in snapshots" :key="snap.id">
          <td>#{{ snap.id }}</td>
          <td>{{ snap.savedAt }}</td>
          <td>{{ snap.label }}</td>
          <td>{{ snap.caliber.version }}</td>
          <td>{{ snap.scope.unit }}</td>
          <td>{{ cardValue(snap, '业务模块') }}</td>
          <td>{{ cardValue(snap, '今日新增') }}</td>
          <td>{{ cardValue(snap, '待处理') }}</td>
          <td>{{ cardValue(snap, '异常量') }}</td>
        </tr>
        <tr v-if="!snapshots.length">
          <td colspan="9" class="empty-state">暂无快照，可点击右上角「保存概览快照」</td>
        </tr>
      </tbody>
    </table>
    <p v-if="snapshotMessage" class="page-desc">{{ snapshotMessage }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, postJson } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Overview = {
  operator: { id: string; name: string; role: string; roleLabel: string; unit: string }
  caliber: { version: string; label: string }
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
  crossUnits: { name: string; hasData: boolean }[]
}

type Snapshot = {
  id: number
  savedAt: string
  label: string
  caliber: { version: string; label: string }
  scope: { operatorId: string; operatorName: string; role: string; unit: string }
  payload: Overview
}

const MODULE_LABELS: Record<string, string> = {
  minearea: '矿区台账', gas: '瓦斯监测', ventilation: '通风系统', roof: '顶板管理',
  waterhazard: '水害防治', rockburst: '冲击地压', personnel: '人员定位', dust: '粉尘防治',
  fireprevent: '防灭火', belt: '皮带运输', hoist: '提升系统', power: '供电系统',
  rescue: '应急救援', training: '安全培训', shift: '入井管理', explosive: '爆破管理',
  roadway: '巷道维修', monitorstation: '监测分站', certificate: '持证管理', emergencydrill: '应急演练',
}

const store = useSessionStore()
const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])
const crossUnits = ref<Overview['crossUnits']>([])
const caliber = ref<Overview['caliber']>({ version: '', label: '' })
const snapshots = ref<Snapshot[]>([])
const errorMessage = ref('')
const snapshotMessage = ref('')

const operatorText = computed(
  () => `${store.operator.name}（${store.operator.roleLabel} · ${store.operator.unit}）`,
)
const caliberText = computed(() => `当前口径 ${caliber.value.version}：${caliber.value.label}`)

function moduleLabel(name: string) {
  return MODULE_LABELS[name] ?? name
}

function cardValue(snap: Snapshot, label: string) {
  return snap.payload.cards.find((card) => card.label === label)?.value ?? '—'
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
    crossUnits.value = payload.crossUnits
    caliber.value = payload.caliber
  } catch (error) {
    cards.value = []
    moduleRows.value = []
    crossUnits.value = []
    errorMessage.value = error instanceof Error ? error.message : '运营概览读取失败'
  }
}

async function reloadSnapshots() {
  try {
    const payload = await fetchJson<{ items: Snapshot[] }>('/api/overview/snapshots')
    snapshots.value = payload.items
  } catch {
    snapshots.value = []
  }
}

async function saveSnapshot() {
  snapshotMessage.value = ''
  try {
    const snap = await postJson<Snapshot>('/api/overview/snapshots', { label: '手动快照' })
    snapshotMessage.value = `快照 #${snap.id} 已按口径 ${snap.caliber.version} 落库（范围：${snap.scope.unit}）`
    await reloadSnapshots()
  } catch (error) {
    snapshotMessage.value = error instanceof Error ? error.message : '快照保存失败'
  }
}

onMounted(() => {
  void reload()
  void reloadSnapshots()
})
</script>
