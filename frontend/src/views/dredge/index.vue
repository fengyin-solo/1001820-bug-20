<template>
  <section class="page" data-module="dredge">
    <header class="page-head">
      <div>
        <h2>清淤疏浚管理</h2>
        <p class="page-desc">维护清淤单，围绕清淤单号、清淤管段、淤积厚度、清淤长度做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记清淤单</button>
        <button class="btn" type="button" @click="exportRows">导出清淤疏浚清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">待安排清淤</span>
        <strong class="stat-value">{{ stats.pending }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">本月清淤长度（米）</span>
        <strong class="stat-value">{{ formatNumber(stats.month_length) }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">本月清出泥量（立方米）</span>
        <strong class="stat-value">{{ formatNumber(stats.mud_volume) }}</strong>
      </article>
    </div>

    <div class="tab-bar">
      <button class="tab" :class="{ active: tab === 'queue' }" type="button" @click="switchTab('queue')">作业队列</button>
      <button class="tab" :class="{ active: tab === 'ledger' }" type="button" @click="switchTab('ledger')">调度台账</button>
    </div>

    <template v-if="tab === 'queue'">
      <form class="filter-bar" @submit.prevent="reload">
        <label class="filter-item">
          <span>清淤单号</span>
          <input v-model="keyword" placeholder="按清淤单号检索" />
        </label>
        <label class="filter-item">
          <span>清淤状态</span>
          <select v-model="statusFilter">
            <option value="">全部状态</option>
            <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">
              <button v-if="column === '清淤单号'" class="link" type="button" @click="openDetail(row)">
                {{ row[column] ?? '—' }}
              </button>
              <template v-else>{{ displayValue(row, column) }}</template>
            </td>
            <td class="row-actions">
              <button
                v-if="row.status === '待安排'"
                class="link"
                type="button"
                @click="openArrange(row)"
              >
                安排清淤
              </button>
              <button
                v-if="row.status === '清淤中'"
                class="link"
                type="button"
                @click="openComplete(row)"
              >
                确认完成
              </button>
              <button
                v-if="row.status === '待安排' || row.status === '清淤中'"
                class="link danger"
                type="button"
                @click="askCancel(row)"
              >
                取消清淤
              </button>
              <span v-else class="muted-text">—</span>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无清淤疏浚数据，可先登记清淤单</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条清淤疏浚记录</span>
        <span class="foot-feedback">
          <span v-if="feedback.ok" class="success-text">{{ feedback.message }}</span>
          <span v-else-if="feedback.message" class="error-text">{{ feedback.message }}</span>
          <button
            v-if="pendingRetry"
            class="link"
            type="button"
            :disabled="submitting"
            @click="retryLastAction"
          >
            断线重试（接着上次提交）
          </button>
        </span>
      </footer>
    </template>

    <template v-else>
      <p class="page-desc" style="margin: 8px 0">
        台账按批次号归并已完成作业：验收结论直接反映到台账，同一批清淤疏浚只计一次，重复开单不会重复累加长度与泥量。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledgerRows" :key="String(row['批次号'])">
            <td v-for="column in ledgerColumns" :key="column">{{ displayValue(row, column) }}</td>
          </tr>
          <tr v-if="!ledgerRows.length">
            <td :colspan="ledgerColumns.length" class="empty-state">暂无已验收的清淤疏浚批次</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>共 {{ ledgerRows.length }} 个清淤批次</span>
        <span v-if="ledgerError" class="error-text">{{ ledgerError }}</span>
      </footer>
    </template>

    <!-- 取消确认 -->
    <div v-if="cancelTarget" class="modal-mask" @click.self="cancelTarget = null">
      <div class="modal">
        <h3>确认取消该清淤单？</h3>
        <p class="page-desc">
          单号 {{ cancelTarget['清淤单号'] }}（{{ cancelTarget['清淤管段'] }}）取消后将退出待安排队列，
          淤积厚度、清出泥量、作业班组等已录入的作业信息会一并清空。
        </p>
        <p class="page-desc">该操作仅用于撤销重复开单；已完成的作业不受影响，也不会退回待安排。</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="cancelTarget = null">再想想</button>
          <button class="btn danger" type="button" :disabled="submitting" @click="confirmCancel">
            {{ submitting ? '提交中…' : '确认取消' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 安排清淤 -->
    <div v-if="arrangeTarget" class="modal-mask" @click.self="arrangeTarget = null">
      <div class="modal">
        <h3>安排清淤：{{ arrangeTarget['清淤单号'] }}</h3>
        <label class="form-item">
          <span>作业班组 *</span>
          <input v-model="arrangeForm['作业班组']" placeholder="如：疏浚一班" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="arrangeTarget = null">关闭</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="confirmArrange">
            {{ submitting ? '提交中…' : '确认安排' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 确认完成（验收） -->
    <div v-if="completeTarget" class="modal-mask" @click.self="completeTarget = null">
      <div class="modal">
        <h3>确认完成：{{ completeTarget['清淤单号'] }}</h3>
        <label class="form-item">
          <span>作业班组</span>
          <input v-model="completeForm['作业班组']" placeholder="承接班组" />
        </label>
        <label class="form-item">
          <span>清淤长度（米）</span>
          <input v-model="completeForm['清淤长度']" placeholder="如：180" />
        </label>
        <label class="form-item">
          <span>清出泥量（立方米）*</span>
          <input v-model="completeForm['清出泥量']" placeholder="如：12.5" />
        </label>
        <label class="form-item">
          <span>验收结论 *</span>
          <select v-model="completeForm['验收结论']">
            <option value="合格">合格</option>
            <option value="不合格">不合格</option>
          </select>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="completeTarget = null">关闭</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="confirmComplete">
            {{ submitting ? '提交中…' : '确认完成并验收' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 登记清淤单 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>登记清淤单</h3>
        <label class="form-item">
          <span>清淤单号 *</span>
          <input v-model="createForm['清淤单号']" placeholder="如：DRED-0010" />
        </label>
        <label class="form-item">
          <span>清淤管段 *</span>
          <input v-model="createForm['清淤管段']" placeholder="如：滨河路 W12-W13" />
        </label>
        <label class="form-item">
          <span>淤积厚度（毫米）*</span>
          <input v-model="createForm['淤积厚度']" placeholder="如：35" />
        </label>
        <label class="form-item">
          <span>批次号（选填，用于台账去重）</span>
          <input v-model="createForm['批次号']" placeholder="如：BATCH-202609-01" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="createOpen = false">关闭</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="confirmCreate">
            {{ submitting ? '提交中…' : '提交登记' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 详情 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <h3>清淤单详情：{{ detail['清淤单号'] }}</h3>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ displayValue(detail, field) }}</dd>
          </template>
        </dl>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/dredge'
const columns = ["清淤单号", "清淤管段", "淤积厚度", "清淤长度", "清出泥量", "作业班组", "完成日期", "清淤状态"]
const ledgerColumns = ["批次号", "清淤管段", "淤积厚度", "清淤长度", "清出泥量", "作业班组", "完成日期", "验收结论", "归并单数"]
const detailFields = ["清淤单号", "批次号", "清淤管段", "淤积厚度", "清淤长度", "清出泥量", "作业班组", "完成日期", "验收结论", "清淤状态"]
const statuses = ["待安排", "清淤中", "已完成", "已取消"]

const tab = ref<'queue' | 'ledger'>('queue')
const rows = ref<Row[]>([])
const total = ref(0)
const keyword = ref('')
const statusFilter = ref('')
const feedback = ref<{ ok: boolean; message: string }>({ ok: false, message: '' })
const stats = ref({ pending: 0, month_length: 0, mud_volume: 0 })
const ledgerRows = ref<Row[]>([])
const ledgerError = ref('')

const submitting = ref(false)
const cancelTarget = ref<Row | null>(null)
const arrangeTarget = ref<Row | null>(null)
const completeTarget = ref<Row | null>(null)
const createOpen = ref(false)
const detail = ref<Row | null>(null)

const arrangeForm = ref<Record<string, string>>({ 作业班组: '' })
const completeForm = ref<Record<string, string>>({ 作业班组: '', 清淤长度: '', 清出泥量: '', 验收结论: '合格' })
const createForm = ref<Record<string, string>>({ 清淤单号: '', 清淤管段: '', 淤积厚度: '', 批次号: '' })

// 最近一次因断线未送达的动作，保留同一个 client_token，点重试时接着走，不会重复流转。
const pendingRetry = ref<{ id: number | string; values: Record<string, unknown> } | null>(null)

function displayValue(row: Row, field: string): string {
  const value = row[field]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function switchTab(next: 'queue' | 'ledger') {
  tab.value = next
  if (next === 'ledger') {
    void loadLedger()
  }
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = { 清淤单号: '', 清淤管段: '', 淤积厚度: '', 批次号: '' }
  createOpen.value = true
}

function openDetail(row: Row) {
  detail.value = row
}

function openArrange(row: Row) {
  arrangeTarget.value = row
  arrangeForm.value = { 作业班组: row['作业班组'] ? String(row['作业班组']) : '' }
}

function openComplete(row: Row) {
  completeTarget.value = row
  completeForm.value = {
    作业班组: row['作业班组'] ? String(row['作业班组']) : '',
    清淤长度: row['清淤长度'] ? String(row['清淤长度']) : '',
    清出泥量: row['清出泥量'] ? String(row['清出泥量']) : '',
    验收结论: '合格',
  }
}

function askCancel(row: Row) {
  cancelTarget.value = row
}

function newToken(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

/** 提交动作；返回 'network' 表示断线，调用方可保留 token 让用户重试。 */
async function postAction(
  id: number | string,
  values: Record<string, unknown>,
  token?: string,
): Promise<'ok' | 'rejected' | 'network'> {
  const clientToken = token ?? newToken()
  values.client_token = clientToken
  try {
    const response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = (await response.json().catch(() => null)) as
      | { ok?: boolean; message?: string }
      | null
    if (!response.ok || !payload) {
      feedback.value = { ok: false, message: payload?.message ?? '清淤疏浚动作未生效，请稍后重试' }
      return 'network'
    }
    if (payload.ok === false) {
      // 业务拒绝（如重复取消已完成单）：原样展示后端原因，不做重试。
      feedback.value = { ok: false, message: payload.message ?? '操作被拒绝' }
      return 'rejected'
    }
    feedback.value = { ok: true, message: payload.message ?? '操作已生效' }
    return 'ok'
  } catch (error) {
    feedback.value = {
      ok: false,
      message: `${error instanceof Error ? error.message : '请求未送达'}（可点“重试”接着走）`,
    }
    pendingRetry.value = { id, values }
    return 'network'
  }
}

async function refreshAfterAction() {
  pendingRetry.value = null
  await Promise.all([reload(), loadStats(), loadLedger(true)])
}

async function confirmCancel() {
  if (!cancelTarget.value) {
    return
  }
  const target = cancelTarget.value
  submitting.value = true
  const result = await postAction(target.id as number, { action: '取消清淤' })
  submitting.value = false
  if (result === 'ok') {
    cancelTarget.value = null
    await refreshAfterAction()
  }
}

async function confirmArrange() {
  if (!arrangeTarget.value) {
    return
  }
  const target = arrangeTarget.value
  submitting.value = true
  const result = await postAction(target.id as number, {
    action: '安排清淤',
    作业班组: arrangeForm.value['作业班组'].trim(),
  })
  submitting.value = false
  if (result === 'ok') {
    arrangeTarget.value = null
    await refreshAfterAction()
  }
}

async function confirmComplete() {
  if (!completeTarget.value) {
    return
  }
  const target = completeTarget.value
  const values: Record<string, unknown> = {
    action: '确认完成',
    清出泥量: completeForm.value['清出泥量'].trim(),
    验收结论: completeForm.value['验收结论'],
  }
  if (completeForm.value['作业班组'].trim()) {
    values.作业班组 = completeForm.value['作业班组'].trim()
  }
  if (completeForm.value['清淤长度'].trim()) {
    values.清淤长度 = completeForm.value['清淤长度'].trim()
  }
  submitting.value = true
  const result = await postAction(target.id as number, values)
  submitting.value = false
  if (result === 'ok') {
    completeTarget.value = null
    await refreshAfterAction()
  }
}

async function confirmCreate() {
  const values: Record<string, unknown> = {
    清淤单号: createForm.value['清淤单号'].trim(),
    清淤管段: createForm.value['清淤管段'].trim(),
    淤积厚度: createForm.value['淤积厚度'].trim(),
  }
  if (createForm.value['批次号'].trim()) {
    values.批次号 = createForm.value['批次号'].trim()
  }
  submitting.value = true
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values }) })
    const payload = (await response.json().catch(() => null)) as
      | { ok?: boolean; message?: string }
      | null
    if (!payload || payload.ok === false) {
      feedback.value = { ok: false, message: payload?.message ?? '登记失败，请检查填写内容' }
    } else {
      createOpen.value = false
      feedback.value = { ok: true, message: payload.message ?? '清淤单已登记' }
      await refreshAfterAction()
    }
  } catch (error) {
    feedback.value = { ok: false, message: error instanceof Error ? error.message : '登记请求未送达' }
  } finally {
    submitting.value = false
  }
}

async function retryLastAction() {
  if (!pendingRetry.value) {
    return
  }
  const { id, values } = pendingRetry.value
  submitting.value = true
  const result = await postAction(id, values, String(values.client_token))
  submitting.value = false
  if (result === 'ok') {
    pendingRetry.value = null
    cancelTarget.value = null
    arrangeTarget.value = null
    completeTarget.value = null
    await refreshAfterAction()
  }
}

async function reload() {
  feedback.value = { ok: false, message: '' }
  const query = new URLSearchParams()
  if (keyword.value.trim()) {
    query.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  const suffix = query.toString()
  try {
    const response = await request(`${ENDPOINT}${suffix ? `?${suffix}` : ''}`)
    if (!response.ok) {
      throw new Error('清淤单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadStats()
  } catch (error) {
    feedback.value = { ok: false, message: error instanceof Error ? error.message : '清淤疏浚列表读取失败' }
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      stats.value = await response.json()
    }
  } catch {
    // 统计读不到不阻塞列表操作，下次刷新再取。
  }
}

async function loadLedger(silent = false) {
  ledgerError.value = ''
  try {
    const response = await request(`${ENDPOINT}/ledger`)
    if (!response.ok) {
      throw new Error('调度台账读取失败')
    }
    const payload = await response.json()
    ledgerRows.value = payload.items ?? []
  } catch (error) {
    if (!silent) {
      ledgerError.value = error instanceof Error ? error.message : '调度台账读取失败'
    }
  }
}

onMounted(reload)
</script>
