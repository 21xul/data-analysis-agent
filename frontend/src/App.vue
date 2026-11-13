<script setup>
/**
 * Insight Agent v2 · 工作台界面
 * 布局对齐已上线 v1 的三栏设计（侧栏 / 顶栏 / 概览卡 / 分析对话 / 数据预览），
 * 但所有数据都来自本地 FastAPI：数据集注册表、LangGraph 逐节点 SSE、确定性统计。
 */
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import * as api from './api/client'
import TracePanel from './components/TracePanel.vue'
import ChartView from './components/ChartView.vue'
import NodeTimeline from './components/NodeTimeline.vue'
import RecallEvidence from './components/RecallEvidence.vue'
import SqlInspector from './components/SqlInspector.vue'

const status = ref(null)
const datasets = ref([])
const activeId = ref('')
const activeName = ref('')
const preview = ref(null)
const stats = ref(null)
const question = ref('')
const engine = ref('langgraph')           // langgraph | react
const branch = ref('')                    // '' 自动 | sql | react
const events = ref([])                    // ReAct 事件
const graphEvents = ref([])               // LangGraph 节点事件
const result = ref(null)                  // 最近一次 final，驱动右侧证据面板
const messages = ref([])                  // 对话消息（各自持有自己的结果快照）
const history = ref([])                   // 分析历史
const loading = ref(false)
const error = ref('')
const busy = ref('')
const toast = ref('')
const importOpen = ref(false)
const inspectorTab = ref('preview')       // preview | evidence
const currentNode = ref('')
const fileInput = ref(null)
const streamBox = ref(null)
let toastTimer = null

const NODE_NAMES = {
  extract_keywords: '理解问题', recall_columns: '字段召回', recall_metrics: '指标召回',
  recall_values: '取值召回', merge_recall: '合并召回', filter_context: '精筛上下文',
  enrich_context: '环境上下文', resolve_dataset: '解析数据集', route_branch: '意图路由',
  generate_sql: '生成 SQL', validate_sql: '校验 SQL', correct_sql: '校正 SQL',
  execute_sql: '只读执行', react_analyze: 'ReAct 分析', synthesize: '汇总结论', finalize: '完成'
}
const EVENT_NAMES = {
  meta: '会话初始化', rag: '口径检索', thought: '推理', action: '调用工具',
  observation: '观察结果', guardrail: '护栏', notice: '提示', final: '生成结论'
}

onMounted(refresh)

// ---------------------------------------------------------------- 数据加载
async function refresh() {
  try {
    status.value = await api.health()
    datasets.value = await api.listDatasets()
    if (!activeId.value && datasets.value.length) {
      await selectDataset(datasets.value[0].id)
    }
  } catch (e) {
    error.value = `后端未就绪：${e.message}（请先启动 uvicorn :8000）`
  }
}

async function selectDataset(id) {
  activeId.value = id
  error.value = ''
  try {
    const [pv, st] = await Promise.all([api.previewDataset(id, 40), api.datasetStats(id)])
    preview.value = pv
    stats.value = st
    activeName.value = pv.name
    messages.value = []
    events.value = []
    graphEvents.value = []
    result.value = null
  } catch (e) {
    error.value = e.message
  }
}

async function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  busy.value = '上传并注册中'
  error.value = ''
  try {
    const ds = await api.uploadDataset(file)
    importOpen.value = false
    await refresh()
    await selectDataset(ds.id)
    notify(`已导入 ${ds.name} · ${ds.rows} 行`)
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = ''
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function loadDemo() {
  busy.value = '生成示例数据中'
  error.value = ''
  try {
    const ds = await api.createDemo()
    importOpen.value = false
    await refresh()
    await selectDataset(ds.id)
    notify('示例数据已生成并注册为只读 SQL 靶')
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = ''
  }
}

// ---------------------------------------------------------------- 计算属性
const statCards = computed(() => {
  const s = stats.value
  if (!s) return [
    { label: '数据行数', value: '—', sub: '等待数据集' },
    { label: '数值字段', value: '—', sub: '等待数据集' },
    { label: '日期字段', value: '—', sub: '等待数据集' },
    { label: '缺失值', value: '—', sub: '等待数据集' },
    { label: '数据规模', value: '—', sub: '等待数据集' }
  ]
  return [
    { label: '数据行数', value: s.rows.toLocaleString('zh-CN'), sub: `共 ${s.columns} 个字段` },
    { label: '数值字段', value: String(s.numeric), sub: s.primary_metric ? `主指标：${s.primary_metric}` : '暂无数值字段' },
    { label: '日期字段', value: String(s.dates), sub: s.date_range ? '已识别时间维度' : '无时间维度' },
    { label: '缺失值', value: String(s.missing), sub: s.missing ? '建议清洗后再分析' : '字段完整' },
    { label: '数据规模', value: `${s.size_kb} KB`, sub: s.date_range ? `${s.date_range.split(' ~ ')[0]} 起` : '本地存储' }
  ]
})

const shortcuts = computed(() => {
  const s = stats.value
  const metric = s?.primary_metric || '销售额'
  const dim = s?.primary_dimension || '渠道'
  const list = []
  if (s?.dates) list.push(`分析${metric}的月度趋势`)
  list.push('找出数据中的异常值并说明原因')
  list.push(`按${dim}对比${metric}`)
  list.push(`统计${metric}合计与均值`)
  list.push('给出整体统计概览和数据质量评估')
  list.push('生成一份综合分析报告')
  return list
})

const qualityChips = computed(() => {
  const s = stats.value
  if (!s) return []
  return [
    { k: '数据行数', v: s.rows.toLocaleString('zh-CN') },
    { k: '字段数', v: `${s.columns} 个` },
    { k: '完整度', v: `${s.completeness}%` },
    { k: '重复行', v: `${s.duplicates} 行` }
  ]
})

const welcomeCards = [
  { title: '数据查询', desc: '按条件取数、聚合统计', q: '统计销售额合计与均值' },
  { title: '趋势分析', desc: '沿时间维度看变化', q: '分析销售额的月度趋势' },
  { title: '异常识别', desc: '定位离群值与尖峰', q: '找出数据中的异常值并说明原因' },
  { title: '综合报告', desc: '一次生成完整结论', q: '生成一份综合分析报告' }
]

const previewCols = computed(() => (preview.value?.columns || []).slice(0, 8))
const nodeCount = computed(() => graphEvents.value.filter(e => e.type === 'node').length)
const evidenceCount = computed(() => engine.value === 'langgraph' ? nodeCount.value : events.value.length)

// ---------------------------------------------------------------- 交互
function notify(text) {
  toast.value = text
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2600)
}

function openImport() { importOpen.value = true }

function switchEngine(name) {
  if (name === engine.value) return
  engine.value = name
  events.value = []
  graphEvents.value = []
  result.value = null
  error.value = ''
  inspectorTab.value = 'evidence'
}

function clearChat() {
  messages.value = []
  events.value = []
  graphEvents.value = []
  result.value = null
  error.value = ''
  notify('对话已清空，分析历史保留')
}

function intentOf(text) {
  if (/报告|综合/.test(text)) return { tag: '综合报告', title: '综合分析报告', cls: 'tag-report' }
  if (/异常|离群/.test(text)) return { tag: '异常识别', title: '异常值分析', cls: 'tag-anomaly' }
  if (/趋势|增长|月度/.test(text)) return { tag: '趋势分析', title: '趋势分析', cls: 'tag-trend' }
  if (/对比|比较|排名/.test(text)) return { tag: '指标对比', title: '指标对比', cls: 'tag-compare' }
  return { tag: '数据查询', title: '数据查询结果', cls: 'tag-query' }
}

function nowTime() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function pushHistory(text) {
  const info = intentOf(text)
  history.value = [{ q: text, tag: info.tag, cls: info.cls, time: nowTime() },
    ...history.value].slice(0, 12)
}

function addStage(m, label) {
  if (!label) return
  if (m.pipeline.length >= 7) return
  if (!m.pipeline.includes(label)) m.pipeline.push(label)
}

async function submit(q) {
  const text = (typeof q === 'string' ? q : question.value).trim()
  if (!text || !activeId.value || loading.value) return
  question.value = ''
  loading.value = true
  error.value = ''
  events.value = []
  graphEvents.value = []
  result.value = null
  currentNode.value = ''
  const info = intentOf(text)
  const m = reactive({
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    question: text, time: nowTime(), engine: engine.value,
    intent: info.tag, title: info.title, status: 'running',
    result: null, err: '', pipeline: [], nodes: 0
  })
  messages.value = [...messages.value, m]
  pushHistory(text)

  const onEvent = (kind, ev) => {
    if (kind === 'node') {
      graphEvents.value = [...graphEvents.value, ev]
      const name = NODE_NAMES[ev.data?.node] || ev.data?.node
      currentNode.value = name || '运行中'
      addStage(m, name)
      m.nodes = graphEvents.value.filter(e => e.type === 'node').length
    } else if (kind === 'final') {
      const data = ev.data || {}
      m.result = data
      m.status = 'done'
      result.value = data
      m.nodes = data.events?.length || m.nodes
      addStage(m, '汇总结论')
      if (engine.value === 'react') events.value = [...events.value, ev]
    } else if (kind === 'error') {
      m.err = ev.data?.message || '运行出错'
      m.status = 'error'
      error.value = m.err
    } else if (kind === 'meta') {
      addStage(m, '会话初始化')
    } else if (engine.value === 'react') {
      events.value = [...events.value, ev]
      m.nodes = events.value.length
      addStage(m, EVENT_NAMES[kind] || kind)
    }
  }

  try {
    if (engine.value === 'react') {
      await api.runAgent(text, activeId.value, onEvent)
    } else {
      await api.runGraphStream(text, activeId.value, branch.value, onEvent)
    }
    if (m.status === 'running') m.status = 'done'
  } catch (err) {
    m.err = err.message
    m.status = 'error'
    error.value = err.message
  } finally {
    loading.value = false
    currentNode.value = ''
  }
}

function exportReport() {
  if (!messages.value.length) { notify('还没有可导出的分析记录'); return }
  const lines = [
    `# Insight Agent · 分析报告`, ``,
    `- 数据集：${activeName.value || '—'}`,
    `- 生成时间：${new Date().toLocaleString('zh-CN')}`,
    `- 编排引擎：${engine.value === 'langgraph' ? 'LangGraph 状态图' : 'ReAct 自主推理'}`,
    `- 规划器：${status.value?.mode === 'real' ? '真实模型' : 'Mock（确定性工具）'}`, ``,
    `## 数据概览`, ``,
    ...(stats.value ? [
      `- ${stats.value.rows} 行 × ${stats.value.columns} 字段，数值字段 ${stats.value.numeric} 个，日期字段 ${stats.value.dates} 个`,
      `- 缺失值 ${stats.value.missing} 个，完整度 ${stats.value.completeness}%，重复行 ${stats.value.duplicates} 行`,
      `- 数据规模 ${stats.value.size_kb} KB${stats.value.date_range ? `，时间范围 ${stats.value.date_range}` : ''}`
    ] : ['- 无']), ``, `## 分析记录`, ``
  ]
  messages.value.forEach((m, i) => {
    lines.push(`### ${i + 1}. ${m.question}（${m.time} · ${m.engine}）`, ``)
    const r = m.result
    if (!r) { lines.push(`- ${m.err || '未完成'}`, ``); return }
    ;(r.conclusions || []).forEach(c => lines.push(`- ${c}`))
    if (r.sql) lines.push(``, `- SQL：\`${r.sql}\``)
    if (r.cross_check?.covered) {
      lines.push(`- 交叉校验：SQL=${r.cross_check.sql_value} / pandas=${r.cross_check.pandas_value}（${r.cross_check.match ? '一致' : '不一致'}）`)
    }
    ;(r.metrics || []).forEach(x => lines.push(`- ${x.k}：${x.v}`))
    ;(r.citations || []).forEach(c => lines.push(`- 引用口径：${c.id || c.title || ''}`))
    lines.push(`- 节点/事件：${m.nodes}`, ``)
  })
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `insight-report-${new Date().toISOString().slice(0, 10)}.md`
  a.click()
  URL.revokeObjectURL(url)
  notify('分析报告已导出为 Markdown')
}

function cell(row, col) {
  const v = row?.[col.key || col.label]
  if (v === null || v === undefined || v === '') return '—'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

function metricVal(v) {
  if (typeof v === 'number') return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  return v == null ? '—' : String(v)
}

function typeLabel(t) {
  return t === 'number' ? '数值' : t === 'date' ? '日期' : '文本'
}

/** 不把确定性工具算出的结论标成「模型生成」：只有 SQL 真由 LLM 产出时才显示模型增强。 */
function conclusionBadge(r) {
  if (r?.sql_source === 'llm') return '模型生成 SQL'
  if (r?.branch === 'react') return '确定性工具'
  return r?.sql ? '模板 SQL' : '确定性工具'
}

watch([() => messages.value.length, () => graphEvents.value.length, () => events.value.length],
  async () => {
    await nextTick()
    if (streamBox.value) streamBox.value.scrollTop = streamBox.value.scrollHeight
  })
</script>

<template>
  <div class="shell">
    <!-- ---------------- 侧栏 ---------------- -->
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">
          <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m7 15 4-5 3 3 5-7"/></svg>
        </div>
        <div class="brand-text"><strong>Insight</strong><span>数据分析 Agent · v2</span></div>
      </div>

      <div class="side-section">
        <div class="side-title">数据集
          <button class="icon-btn" title="导入数据" @click="openImport">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
          </button>
        </div>
        <div class="dataset-list">
          <div v-for="d in datasets" :key="d.id" class="ds-item" :class="{ active: d.id === activeId }"
               @click="selectDataset(d.id)">
            <span class="ds-icon">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>
            </span>
            <div class="ds-meta">
              <div class="ds-name">{{ d.name }}</div>
              <div class="ds-sub">{{ d.id === activeId && stats ? `${stats.rows} 行 · ${stats.columns} 字段` : '本地数据集' }}</div>
            </div>
          </div>
          <div v-if="!datasets.length" class="side-empty">还没有数据集，点击右上角 + 导入 CSV 或生成示例数据。</div>
        </div>
      </div>

      <div class="side-section grow">
        <div class="side-title">分析历史 <span class="count-badge">{{ history.length }}</span></div>
        <div class="history-list">
          <div v-for="(h, i) in history" :key="i" class="hist-item" @click="submit(h.q)">
            <span class="hist-tag" :class="h.cls">{{ h.tag }}</span>
            <span class="hist-text">{{ h.q }}</span>
          </div>
          <div v-if="!history.length" class="side-empty">提问后，这里会保留最近 12 条分析记录，点击可重跑。</div>
        </div>
      </div>

      <div class="sidebar-foot">
        <div class="engine-pill">
          <span class="dot"></span>
          <div>
            <strong>{{ status?.mode === 'real' ? '真实模型 · 在线' : '本地原型 · 确定性工具' }}</strong>
            <span>{{ engine === 'langgraph' ? 'LangGraph 17 节点编排' : 'ReAct 自主推理' }} · SQLite</span>
          </div>
        </div>
        <div class="user-row">
          <span class="user-name">{{ status?.tools?.length || 0 }} 个工具 · {{ status?.model || (status?.mode === 'real' ? '在线模型' : 'Mock 规划器') }}</span>
          <button class="text-link" @click="clearChat">清空对话</button>
        </div>
      </div>
    </aside>

    <!-- ---------------- 主区 ---------------- -->
    <main class="main">
      <header class="topbar">
        <div class="crumb">
          <span>工作台</span>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg>
          <strong>{{ activeName || '未选择数据集' }}</strong>
        </div>
        <div class="top-actions">
          <button class="btn ghost" :disabled="!activeId || loading" @click="submit('生成一份综合分析报告')">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg>智能报告
          </button>
          <button class="btn ghost" :disabled="!messages.length" @click="exportReport">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3v12M7 10l5 5 5-5M4 17v3h16v-3"/></svg>导出
          </button>
          <button class="btn primary" @click="openImport">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>导入数据
          </button>
        </div>
      </header>

      <!-- 空状态 -->
      <div v-if="!activeId" class="empty-state">
        <div class="empty-illustration">
          <svg viewBox="0 0 120 96" width="150" height="120" fill="none">
            <rect x="8" y="14" width="104" height="72" rx="10" fill="#eef0ff" stroke="#d9dcff" stroke-width="2"/>
            <path d="M24 70V52M44 70V40M64 70V58M84 70V30M100 70V46" stroke="#7b7ce6" stroke-width="7" stroke-linecap="round"/>
            <circle cx="88" cy="20" r="11" fill="#fff" stroke="#7b7ce6" stroke-width="2"/>
            <path d="m84 20 3 3 5-6" stroke="#7b7ce6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <h1>把数据交给 Agent，直接问出结论</h1>
        <p>上传 CSV 或加载示例数据，Agent 会自动注册为只读 SQL 靶并同步元数据；随后可用自然语言查询、分析趋势、识别异常、对比指标，过程按 LangGraph 节点逐步可见。</p>
        <div class="empty-actions">
          <button class="btn primary big" @click="fileInput?.click()">上传 CSV 文件</button>
          <button class="btn ghost big" :disabled="!!busy" @click="loadDemo">加载示例数据</button>
        </div>
        <div class="empty-hint">本地原型 · 前后端分离 · 数据只保存在本机 SQLite</div>
        <p v-if="error" class="err-bar">{{ error }}</p>
      </div>

      <!-- 工作台 -->
      <div v-else class="workspace">
        <section class="overview">
          <div v-for="(c, i) in statCards" :key="i" class="stat-card">
            <div class="stat-label">{{ c.label }}</div>
            <div class="stat-value">{{ c.value }}</div>
            <div class="stat-sub">{{ c.sub }}</div>
          </div>
        </section>

        <section class="workspace-grid">
          <!-- 分析对话 -->
          <div class="chat-card">
            <div class="chat-head">
              <div class="chat-head-left">
                <div class="avatar">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2 2 7l10 5 10-5-10-5Z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/></svg>
                </div>
                <div>
                  <strong>分析对话</strong>
                  <span>用自然语言提问，Agent 自动完成取数、计算与作图</span>
                </div>
              </div>
              <button class="btn tiny ghost" @click="clearChat">清空对话</button>
            </div>

            <div class="chat-stream" ref="streamBox">
              <div v-if="!messages.length" class="welcome-msg">
                <strong>你好，我已读取「{{ activeName }}」的字段与取值</strong>
                <span>可以从下方选一个分析方向，或直接描述你想知道的结论。数字由确定性工具计算，过程可在右侧「执行证据」查看。</span>
                <div class="welcome-cards">
                  <button v-for="c in welcomeCards" :key="c.title" class="welcome-card" @click="submit(c.q)">
                    <b>{{ c.title }}</b><small>{{ c.desc }}</small>
                  </button>
                </div>
              </div>

              <template v-for="m in messages" :key="m.id">
                <div class="msg-user">{{ m.question }}</div>
                <div class="msg-agent">
                  <div class="agent-avatar">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m12 2 2 6 6 2-6 2-2 6-2-6-6-2 6-2Z"/></svg>
                  </div>
                  <div class="agent-body">
                    <!-- 运行中 -->
                    <div v-if="m.status === 'running'" class="result-card running-card">
                      <div class="typing"><i></i><i></i><i></i></div>
                      <span class="running-text">{{ currentNode || '正在理解问题…' }} · 已完成 {{ m.nodes }} 个节点</span>
                      <div v-if="m.pipeline.length" class="pipeline">
                        <template v-for="(p, i) in m.pipeline" :key="i">
                          <span v-if="i" class="pipe-arrow">›</span><span class="pipe-step">{{ p }}</span>
                        </template>
                      </div>
                    </div>

                    <!-- 出错 -->
                    <div v-else-if="m.status === 'error'" class="result-card err-bar">{{ m.err || '运行失败' }}</div>

                    <!-- 结果卡片 -->
                    <div v-else-if="m.status === 'done' && m.result" class="result-card">
                      <div class="result-top">
                        <span class="intent-tag">{{ m.intent }}</span>
                        <span class="result-title">{{ m.title }}</span>
                        <span v-if="m.result?.branch" class="branch-tag">{{ m.result.branch === 'sql' ? 'SQL 闭环' : 'ReAct 分析' }}</span>
                        <span class="result-time">{{ m.time }}</span>
                      </div>

                      <div v-if="m.pipeline.length" class="pipeline">
                        <template v-for="(p, i) in m.pipeline" :key="i">
                          <span v-if="i" class="pipe-arrow">›</span><span class="pipe-step">{{ p }}</span>
                        </template>
                      </div>

                      <div v-if="m.result" class="conclusion">
                        <div class="conclusion-head">
                          Agent 分析结论
                          <span class="ai-badge" :class="{ local: conclusionBadge(m.result) !== '模型生成 SQL' }">
                            {{ conclusionBadge(m.result) }}
                          </span>
                        </div>
                        <ul>
                          <li v-for="(c, i) in m.result.conclusions || []" :key="i">{{ c }}</li>
                          <li v-if="!m.result.conclusions?.length">本次未产出文字结论，请查看右侧执行证据。</li>
                        </ul>
                      </div>

                      <div v-if="m.result?.metrics?.length" class="metric-row">
                        <div v-for="(x, i) in m.result.metrics" :key="i" class="metric-chip">
                          <div class="k">{{ x.k }}</div><div class="v">{{ metricVal(x.v) }}</div>
                        </div>
                      </div>

                      <div v-if="qualityChips.length" class="quality-block">
                        <div class="quality-title">数据概览与质量</div>
                        <div class="metric-row">
                          <div v-for="(x, i) in qualityChips" :key="i" class="metric-chip">
                            <div class="k">{{ x.k }}</div><div class="v" :class="{ warn: x.k === '重复行' && stats?.duplicates }">{{ x.v }}</div>
                          </div>
                        </div>
                      </div>

                      <div v-if="m.result?.charts?.length" class="chart-box">
                        <ChartView v-for="(c, i) in m.result.charts" :key="i" :chart="c" />
                      </div>

                      <div v-for="(t, ti) in m.result?.tables || []" :key="ti" class="result-table-wrap">
                        <div class="result-table-head"><span>{{ t.title || '数据明细' }}</span><span>{{ (t.rows || []).length }} 行</span></div>
                        <div class="result-table-scroll">
                          <table class="grid">
                            <thead><tr><th v-for="c in t.columns" :key="c">{{ c }}</th></tr></thead>
                            <tbody><tr v-for="(r, ri) in t.rows" :key="ri"><td v-for="c in t.columns" :key="c">{{ r[c] }}</td></tr></tbody>
                          </table>
                        </div>
                      </div>

                      <div class="result-foot">
                        <span>{{ m.engine === 'langgraph' ? 'LangGraph' : 'ReAct' }} · {{ m.nodes }} 节点/事件</span>
                        <span v-if="m.result?.elapsed_ms">{{ m.result.elapsed_ms }} ms</span>
                        <span v-if="m.result?.sql">SQL：{{ m.result.sql }}</span>
                        <span v-if="m.result?.citations?.length">引用口径 {{ m.result.citations.length }} 条</span>
                        <button class="btn tiny ghost" @click="inspectorTab = 'evidence'">查看执行证据 →</button>
                      </div>

                    <div v-if="m.status === 'done' && !m.result" class="result-card muted small">本次运行未返回结论载荷。</div>
                    </div>
                  </div>
                </div>
              </template>

              <p v-if="error && !messages.length" class="err-bar">{{ error }}</p>
            </div>

            <!-- 输入区 -->
            <div class="composer">
              <div class="chips">
                <button v-for="s in shortcuts" :key="s" class="chip" :disabled="loading" @click="submit(s)">{{ s }}</button>
              </div>
              <div class="input-row">
                <textarea v-model="question" rows="2"
                          placeholder="例如：分析销售额的月度趋势，找出异常月份，并按渠道对比表现…"
                          :disabled="loading" @keydown.enter.exact.prevent="submit()"></textarea>
                <button class="ask-btn" :disabled="loading" title="开始分析" @click="submit()">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>
                </button>
              </div>
              <div class="composer-foot">
                <span>Enter 发送 · Shift + Enter 换行</span>
                <span class="foot-right">
                  <span class="segmented">
                    <button :class="{ on: engine === 'langgraph' }" @click="switchEngine('langgraph')">LangGraph</button>
                    <button :class="{ on: engine === 'react' }" @click="switchEngine('react')">ReAct</button>
                  </span>
                  <select v-if="engine === 'langgraph'" v-model="branch" class="branch-select" :disabled="loading">
                    <option value="">自动路由</option>
                    <option value="sql">强制 SQL</option>
                    <option value="react">强制 ReAct</option>
                  </select>
                  <span class="mini-status">{{ status?.mode === 'real' ? '真实模型' : 'Mock 规划器' }} · 本地数据</span>
                </span>
              </div>
            </div>
          </div>

          <!-- 右侧检查器 -->
          <aside class="inspector">
            <div class="inspector-head">
              <div class="inspector-tabs">
                <button :class="{ active: inspectorTab === 'preview' }" @click="inspectorTab = 'preview'">数据预览</button>
                <button :class="{ active: inspectorTab === 'evidence' }" @click="inspectorTab = 'evidence'">
                  执行证据 <span class="count-badge">{{ evidenceCount }}</span>
                </button>
              </div>
              <button class="btn tiny ghost" @click="openImport">导入</button>
            </div>

            <template v-if="inspectorTab === 'preview'">
              <div class="field-list">
                <span v-for="c in preview?.columns || []" :key="c.key || c.label" class="field-chip">
                  <b>{{ c.label }}</b><span class="t" :class="'t-' + c.type">{{ typeLabel(c.type) }}</span>
                </span>
              </div>
              <div class="preview-wrap">
                <table class="preview-table">
                  <thead><tr><th v-for="c in previewCols" :key="c.key || c.label">{{ c.label }}</th></tr></thead>
                  <tbody>
                    <tr v-for="(r, i) in preview?.rows || []" :key="i">
                      <td v-for="c in previewCols" :key="c.key || c.label">{{ cell(r, c) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="preview-foot">显示 {{ preview?.shown || 0 }} / {{ preview?.total || 0 }} 行 · 示例前 {{ previewCols.length }} 列 · 可横向滚动</div>
            </template>

            <div v-else class="evidence-scroll">
              <template v-if="engine === 'langgraph'">
                <NodeTimeline :events="graphEvents" :running="loading" />
                <RecallEvidence :evidence="result?.recall_evidence || {}" />
                <SqlInspector :final="result" />
              </template>
              <TracePanel v-else :events="events" />
              <p v-if="!evidenceCount && !result" class="side-empty">提问后，这里按节点实时显示召回、SQL 校验、交叉校验与推理轨迹。</p>
            </div>
          </aside>
        </section>
      </div>
    </main>
  </div>

  <!-- 导入弹窗 -->
  <div v-if="importOpen" class="modal-backdrop" @click.self="importOpen = false">
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <strong>导入数据</strong>
        <button class="icon-btn" aria-label="关闭" @click="importOpen = false">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>
      <div class="modal-body">
        <div class="import-grid">
          <button class="import-card" :disabled="!!busy" @click="fileInput?.click()">
            <span class="dz-icon"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 9l5-5 5 5M12 4v12"/></svg></span>
            <strong>上传 CSV 文件</strong>
            <span>自动识别字段类型，注册为只读数据表</span>
          </button>
          <button class="import-card" :disabled="!!busy" @click="loadDemo">
            <span class="dz-icon"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 3v18h18"/><path d="m7 15 4-5 3 3 5-7"/></svg></span>
            <strong>加载示例数据</strong>
            <span>48 行电商渠道数据，含一处可定位异常</span>
          </button>
        </div>
        <div class="inline-note">导入后会自动写入数据集注册表（<code>ds_&lt;id&gt;</code> 物理表）并增量同步字段/取值到元数据知识库；SQL 分支只通过 <code>mode=ro</code> 只读连接执行，结果再与 pandas 交叉校验。</div>
        <p v-if="busy" class="muted small">{{ busy }}…</p>
        <p v-if="error" class="err-bar">{{ error }}</p>
      </div>
    </div>
  </div>

  <div v-if="toast" class="toast">{{ toast }}</div>
  <input ref="fileInput" type="file" accept=".csv,.txt" hidden @change="onFile" />
</template>
