<template>
  <section class="page" data-module="dredge">
    <header class="page-head">
      <div>
        <h2>清淤疏浚管理</h2>
        <p class="page-desc">维护清淤单，围绕清淤单号、批次号、淤积厚度做登记、筛选与状态流转；重复开单可直接取消，验收结论同步调度台账。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出清淤疏浚清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>清淤单号</span>
        <input v-model="keyword" placeholder="按清淤单号检索" />
      </label>
      <label class="filter-item">
        <span>清淤状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
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
            <template v-else>{{ display(row, column) }}</template>
          </td>
          <td class="row-actions">
            <template v-if="allowedActions(row.status).length">
              <button
                v-for="action in allowedActions(row.status)"
                :key="action"
                class="link"
                :disabled="busyKey === busyId(row, action)"
                type="button"
                @click="onAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无清淤疏浚数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条清淤疏浚记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <h3 class="ledger-title">清淤疏浚调度台账（同一批次只算一次）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in ledgerRows" :key="String(row.批次号)">
          <td v-for="column in ledgerColumns" :key="column">{{ row[column] ?? '—' }}</td>
        </tr>
        <tr v-if="!ledgerRows.length">
          <td :colspan="ledgerColumns.length" class="empty-state">暂无已验收批次</td>
        </tr>
      </tbody>
    </table>

    <!-- 详情：每次都按 id 重新拉取，刷新页面或再次进入看到的口径与列表一致 -->
    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <div class="modal-head">
          <strong>清淤单详情 · {{ detail.清淤单号 }}</strong>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </div>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ display(detail, field) }}</dd>
          </template>
        </dl>
        <div v-if="detailError" class="error-text">{{ detailError }}</div>
        <div class="modal-actions">
          <button
            v-for="action in allowedActions(detail.status)"
            :key="action"
            class="btn"
            :class="{ primary: action !== '取消清淤' }"
            type="button"
            @click="onAction(action, detail)"
          >
            {{ action }}
          </button>
        </div>
      </div>
    </div>

    <!-- 取消确认 -->
    <div v-if="confirmCancel" class="modal-mask" @click.self="confirmCancel = null">
      <div class="modal modal-sm">
        <div class="modal-head"><strong>取消清淤单</strong></div>
        <p>确认取消清淤单「{{ confirmCancel.清淤单号 }}」（批次 {{ confirmCancel.批次号 }}）？</p>
        <p class="muted-text">取消后该单退出待安排队列，淤积厚度、清出泥量等作业字段一并清空；已完成作业不会被退回。</p>
        <div v-if="actionError" class="error-text">{{ actionError }}</div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" :disabled="submitting" @click="confirmCancel = null">再想想</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCancel">
            {{ submitting ? '提交中…' : '确认取消' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 完工验收 -->
    <div v-if="completeTarget" class="modal-mask" @click.self="completeTarget = null">
      <div class="modal modal-sm">
        <div class="modal-head"><strong>确认完成 · {{ completeTarget.清淤单号 }}</strong></div>
        <label class="form-item">
          <span>验收结论</span>
          <select v-model="acceptResult">
            <option value="验收合格">验收合格</option>
            <option value="验收不合格">验收不合格</option>
          </select>
        </label>
        <label class="form-item">
          <span>清淤长度（如 260m，可留空沿用已填值）</span>
          <input v-model="completeForm.清淤长度" placeholder="260m" />
        </label>
        <label class="form-item">
          <span>清出泥量（如 12.5t）</span>
          <input v-model="completeForm.清出泥量" placeholder="12.5t" />
        </label>
        <label class="form-item">
          <span>作业班组</span>
          <input v-model="completeForm.作业班组" />
        </label>
        <div v-if="actionError" class="error-text">{{ actionError }}</div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" :disabled="submitting" @click="completeTarget = null">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitComplete">
            {{ submitting ? '提交中…' : '确认完成' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type LedgerRow = Record<string, string | number | null>

const ENDPOINT = '/api/dredge'
const columns = ["清淤单号", "批次号", "清淤管段", "淤积厚度", "清淤长度", "清出泥量", "作业班组", "完成日期", "验收结论", "清淤状态"]
const ledgerColumns = ["批次号", "清淤管段", "代表单号", "关联单数", "清淤长度", "清出泥量", "完成日期", "验收结论"]
const detailFields = ["批次号", "清淤管段", "淤积厚度", "清淤长度", "清出泥量", "作业班组", "完成日期", "验收结论", "清淤状态"]
const statuses = ["待安排", "清淤中", "已完成", "已取消"]
// 各状态下允许的动作；已完成/已取消不给任何动作，避免重复取消把完工单退回队列。
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  '待安排': ['安排清淤', '取消清淤'],
  '清淤中': ['确认完成'],
  '已完成': [],
  '已取消': [],
}

const rows = ref<Row[]>([])
const ledgerRows = ref<LedgerRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const busyKey = ref('')

const statCards = ref([
  { label: '待安排清淤', value: 0 as number | string },
  { label: '本月清淤长度(m)', value: 0 as number | string },
  { label: '清出泥量(t)', value: 0 as number | string },
])

const detail = ref<Row | null>(null)
const detailError = ref('')
const confirmCancel = ref<Row | null>(null)
const completeTarget = ref<Row | null>(null)
const acceptResult = ref('验收合格')
const completeForm = reactive({ 清淤长度: '', 清出泥量: '', 作业班组: '' })
const actionError = ref('')
const submitting = ref(false)

function allowedActions(status: unknown): string[] {
  return ACTIONS_BY_STATUS[String(status)] ?? []
}

function busyId(row: Row, action: string) {
  return `${String(row.id)}:${action}`
}

function display(row: Row, field: string): string | number | null {
  const value = row[field]
  return value === null || value === undefined || value === '' ? '—' : value
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openDetail(row: Row) {
  detail.value = row
  detailError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      detailError.value = '清淤单详情读取失败'
      return
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '清淤单详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
  detailError.value = ''
}

function onAction(action: string, row: Row) {
  actionError.value = ''
  if (action === '取消清淤') {
    confirmCancel.value = row
    return
  }
  if (action === '确认完成') {
    completeTarget.value = row
    acceptResult.value = '验收合格'
    completeForm.清淤长度 = ''
    completeForm.清出泥量 = ''
    completeForm.作业班组 = ''
  } else {
    void dispatchAction(action, row, {})
  }
}

async function submitCancel() {
  if (!confirmCancel.value) return
  const target = confirmCancel.value
  await dispatchAction('取消清淤', target, {})
  if (!actionError.value) confirmCancel.value = null
}

async function submitComplete() {
  if (!completeTarget.value) return
  const target = completeTarget.value
  const values: Record<string, string> = { 验收结论: acceptResult.value }
  for (const field of ['清淤长度', '清出泥量', '作业班组'] as const) {
    if (completeForm[field].trim()) values[field] = completeForm[field].trim()
  }
  await dispatchAction('确认完成', target, values)
  if (!actionError.value) completeTarget.value = null
}

/**
 * 提交动作。报文包在 values 里；带 request_id，
 * 网络中断或 5xx 时用同一编号继续重试，后端按编号幂等，不会重复执行。
 */
async function dispatchAction(action: string, row: Row, values: Record<string, string>) {
  actionError.value = ''
  submitting.value = true
  busyKey.value = busyId(row, action)
  const requestId = `dredge-${row.id}-${action}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const body = JSON.stringify({ values: { action, request_id: requestId, ...values } })
  try {
    const result = await postWithRetry(`${ENDPOINT}/${row.id}/actions`, body, requestId)
    if (!result.ok) {
      // 业务校验失败：展示后端给出的原因（如已完成不能取消）。
      actionError.value = result.message
      return
    }
    errorMessage.value = ''
    // 队列、字段、概览待处理量来自同一份后端数据，确认后一起刷新。
    await Promise.all([reload(), refreshDetailAfterAction(Number(row.id))])
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '清淤疏浚操作失败'
  } finally {
    submitting.value = false
    busyKey.value = ''
  }
}

async function postWithRetry(url: string, body: string, requestId: string, retries = 2) {
  let lastError: unknown = null
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await request(url, { method: 'POST', body })
      if (response.ok) {
        const payload = (await response.json().catch(() => null)) as { ok?: boolean; message?: string } | null
        return { ok: Boolean(payload?.ok), message: payload?.message ?? '清淤疏浚动作未生效' }
      }
      if (response.status >= 500) {
        // 服务端可能已执行成功，带同一 request_id 重试，拿到首次结果。
        lastError = new Error(`服务暂不可用（${response.status}），正在重试…`)
        continue
      }
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null
      return { ok: false, message: payload?.detail ?? `清淤疏浚动作未生效（${response.status}）` }
    } catch (error) {
      // 请求未送达（断线）：接着重试。
      lastError = error
    }
  }
  throw lastError instanceof Error
    ? new Error(`网络中断后多次重试仍失败（请求编号 ${requestId}），请检查网络后重试，后台不会重复执行`)
    : new Error('清淤疏浚动作未送达')
}

async function refreshDetailAfterAction(id: number) {
  if (!detail.value || Number(detail.value.id) !== id) return
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    if (response.ok) detail.value = (await response.json()) as Row
  } catch {
    // 列表已刷新成功，详情下次打开再取即可
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  query.set('page', '1')
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('清淤单列表读取失败')
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '清淤疏浚列表读取失败'
  }
  void loadStats()
  void loadLedger()
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const payload = (await response.json()) as Record<string, number>
    statCards.value[0].value = payload.待安排清淤 ?? 0
    statCards.value[1].value = payload.本月清淤长度 ?? 0
    statCards.value[2].value = payload.清出泥量 ?? 0
  } catch {
    // 统计拉取失败不阻塞列表
  }
}

async function loadLedger() {
  try {
    const response = await request(`${ENDPOINT}/ledger`)
    if (!response.ok) return
    const payload = (await response.json()) as { items?: LedgerRow[] }
    ledgerRows.value = payload.items ?? []
  } catch {
    // 台账拉取失败不阻塞列表
  }
}

onMounted(reload)
</script>

<style scoped>
.muted-text { color: var(--muted); font-size: 12px; }
.ledger-title { margin: 20px 0 8px; font-size: 15px; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 20;
}
.modal {
  background: #fff; border-radius: 8px; padding: 16px 18px;
  width: 640px; max-width: 92vw; max-height: 86vh; overflow: auto;
}
.modal-sm { width: 420px; }
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.detail-grid { display: grid; grid-template-columns: 110px 1fr 110px 1fr; gap: 6px 10px; margin: 0; font-size: 13px; }
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.form-item { display: block; margin-bottom: 10px; font-size: 12px; color: var(--muted); }
.form-item span { display: block; margin-bottom: 4px; }
.form-item input, .form-item select { width: 100%; box-sizing: border-box; padding: 6px 8px; }
.filter-item select { padding: 6px 8px; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
