<script setup>
import { computed } from 'vue'

const props = defineProps({ evidence: { type: Object, default: () => ({}) } })

const routes = computed(() => props.evidence.routes || {})
const tables = computed(() => props.evidence.tables || [])
const columns = computed(() => props.evidence.columns || [])
const metrics = computed(() => props.evidence.metrics || [])
const values = computed(() => props.evidence.values || [])
const filter = computed(() => props.evidence.filter || null)
const hasAny = computed(() => tables.value.length || columns.value.length || metrics.value.length || values.value.length)
</script>

<template>
  <section class="panel evidence">
    <header class="panel-head">
      <h2>召回证据 <span class="muted small">三路混合召回 + RRF</span></h2>
      <span class="badge">{{ columns.length }} 字段 · {{ metrics.length }} 指标 · {{ values.length }} 取值</span>
    </header>

    <div class="ev-routes">
      <div class="ev-route"><b>{{ routes.columns ?? 0 }}</b><small>字段路 · 向量+别名</small></div>
      <div class="ev-route"><b>{{ routes.metrics ?? 0 }}</b><small>指标路 · 向量+别名</small></div>
      <div class="ev-route"><b>{{ routes.values ?? 0 }}</b><small>取值路 · FTS5</small></div>
    </div>

    <div v-if="filter" class="ev-filter">
      精筛策略 <b>{{ filter.strategy }}</b> · 表 {{ filter.tables_before }} → {{ filter.tables_after }} · 指标 {{ filter.metrics_after }}
    </div>

    <p v-if="!hasAny" class="muted small">本次提问没有命中元数据，SQL 分支将只依赖数据集 schema。</p>

    <div v-if="tables.length" class="ev-block">
      <h3>命中表</h3>
      <div class="chips">
        <span v-for="t in tables" :key="t.id" class="chip ev-chip">{{ t.name }}<i>{{ t.role }}</i></span>
      </div>
    </div>

    <div v-if="columns.length" class="ev-block">
      <h3>字段（含补齐的主外键）</h3>
      <div class="table-wrap ev-table">
        <table>
          <thead><tr><th>字段</th><th>所属表</th><th>类型</th><th>角色</th></tr></thead>
          <tbody>
            <tr v-for="c in columns" :key="c.id">
              <td><b>{{ c.name }}</b></td><td>{{ c.table_id }}</td><td>{{ c.type }}</td><td>{{ c.role }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="metrics.length" class="ev-block">
      <h3>指标口径</h3>
      <div class="ev-list">
        <div v-for="m in metrics" :key="m.id" class="ev-line"><b>{{ m.name }}</b><span>{{ m.description }}</span></div>
      </div>
    </div>

    <div v-if="values.length" class="ev-block">
      <h3>取值映射</h3>
      <div class="chips">
        <span v-for="(v, i) in values" :key="i" class="chip ev-chip ev-value">
          {{ v.value }}<i>{{ (v.column_id || '').split('.').pop() }}</i>
        </span>
      </div>
    </div>
  </section>
</template>
