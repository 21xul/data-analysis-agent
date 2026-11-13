<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  events: { type: Array, default: () => [] },
  running: { type: Boolean, default: false }
})

const box = ref(null)
const names = {
  extract_keywords: '理解问题', recall_columns: '字段召回', recall_metrics: '指标召回',
  recall_values: '取值召回', merge_recall: '合并召回', filter_context: '精筛上下文',
  enrich_context: '环境上下文', resolve_dataset: '解析数据集', route_branch: '意图路由',
  generate_sql: '生成 SQL', validate_sql: '校验 SQL', correct_sql: '校正 SQL',
  execute_sql: '执行 SQL', react_analyze: 'ReAct 分析', synthesize: '汇总结论',
  finalize: '完成'
}
const groups = {
  extract_keywords: 'understand', recall_columns: 'recall', recall_metrics: 'recall',
  recall_values: 'recall', merge_recall: 'recall', filter_context: 'recall',
  enrich_context: 'context', resolve_dataset: 'context', route_branch: 'branch',
  generate_sql: 'sql', validate_sql: 'sql', correct_sql: 'sql', execute_sql: 'sql',
  react_analyze: 'react', synthesize: 'final', finalize: 'final'
}
const keyHints = ['branch', 'table', 'rows', 'count', 'ok', 'error', 'registered',
                  'source', 'covered', 'match', 'values', 'keywords', 'strategy']

const nodes = computed(() => props.events.filter(e => e.type === 'node'))

function summary(ev) {
  const d = ev.data?.detail || {}
  const bits = []
  for (const k of keyHints) {
    if (d[k] === undefined || d[k] === null || d[k] === '') continue
    let v = d[k]
    if (Array.isArray(v)) v = v.slice(0, 4).join('、') + (v.length > 4 ? '…' : '')
    else if (typeof v === 'object') v = JSON.stringify(v).slice(0, 60)
    bits.push(`${k}=${v}`)
    if (bits.length >= 3) break
  }
  return bits.join(' · ') || '已完成'
}

function pretty(ev) {
  try { return JSON.stringify(ev.data?.detail || {}, null, 2) } catch { return '' }
}

watch(() => props.events.length, async () => {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
})
</script>

<template>
  <section class="panel trace">
    <header class="panel-head">
      <h2>节点时间线 <span class="muted small">LangGraph</span></h2>
      <span class="badge">{{ nodes.length }} 节点<span v-if="running"> · 运行中</span></span>
    </header>
    <div class="trace-body tl-body" ref="box">
      <p v-if="!nodes.length" class="muted">切换为 LangGraph 引擎并提问后，这里按节点实时展示编排过程。</p>
      <div v-for="(ev, i) in nodes" :key="ev.id || i" class="tl-item" :class="'g-' + (groups[ev.data?.node] || 'other')">
        <div class="tl-rail"><span class="tl-dot"></span></div>
        <div class="tl-content">
          <div class="tl-head">
            <b>{{ names[ev.data?.node] || ev.data?.node }}</b>
            <span class="tl-stage">{{ ev.data?.stage }}</span>
            <span class="tl-ts">{{ ev.ts }} ms</span>
          </div>
          <div class="tl-sum">{{ summary(ev) }}</div>
          <details class="tl-detail">
            <summary>节点数据</summary>
            <pre>{{ pretty(ev) }}</pre>
          </details>
        </div>
      </div>
    </div>
  </section>
</template>
