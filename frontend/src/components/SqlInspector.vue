<script setup>
import { computed } from 'vue'

const props = defineProps({ final: { type: Object, default: null } })

const rows = computed(() => props.final?.sql_rows || [])
const cols = computed(() => rows.value.length ? Object.keys(rows.value[0]) : [])
const check = computed(() => props.final?.cross_check || {})
const schema = computed(() => props.final?.dataset_schema || {})
const isReact = computed(() => props.final?.branch === 'react')
</script>

<template>
  <section v-if="final" class="panel sql-panel">
    <header class="panel-head">
      <h2>SQL 闭环 <span class="muted small">生成 → 校验 → 纠错 → 只读执行</span></h2>
      <span class="badge" :class="final.sql_ok ? 'ok' : 'bad'">
        {{ isReact ? 'ReAct 分支' : (final.sql_ok ? '校验通过' : '未通过') }}
      </span>
    </header>

    <div v-if="isReact" class="muted small">本次走 ReAct 自主分析分支，未生成 SQL。切换「强制 SQL」可查看闭环轨迹。</div>

    <template v-else>
      <div class="sql-meta">
        <span><small>来源</small>{{ final.sql_source || '—' }}</span>
        <span><small>纠错</small>{{ final.corrections }} / {{ final.max_sql_corrections }}</span>
        <span><small>返回行</small>{{ rows.length }}</span>
        <span><small>执行靶</small>{{ schema.table || '元数据表' }}</span>
      </div>

      <pre class="sql-code">{{ final.sql || '（未生成 SQL）' }}</pre>
      <p v-if="final.sql_error" class="err small">校验未通过：{{ final.sql_error }}</p>

      <div v-if="Object.keys(check).length" class="sql-check" :class="check.match === true ? 'ok' : (check.covered ? 'bad' : 'neutral')">
        <div class="sql-check-head">
          <b>交叉校验</b>
          <span>{{ check.covered ? (check.match ? '一致 ✓' : '不一致 ✗') : '未覆盖' }}</span>
        </div>
        <div v-if="check.covered" class="sql-values">
          <span><small>SQL</small>{{ check.sql_value }}</span>
          <span><small>pandas</small>{{ check.pandas_value }}</span>
        </div>
        <p class="small">{{ check.note }}</p>
      </div>

      <div v-if="schema.columns?.length" class="ev-block">
        <h3>已注册数据集 schema</h3>
        <div class="chips">
          <span v-for="c in schema.columns" :key="c.name" class="chip ev-chip">
            {{ c.name }}<i>{{ c.type }}</i>
          </span>
        </div>
        <p class="muted small">表名 {{ schema.table }} · {{ schema.row_count }} 行 · 只读连接执行</p>
      </div>

      <div v-if="cols.length" class="table-wrap ev-table">
        <table>
          <thead><tr><th v-for="c in cols" :key="c">{{ c }}</th></tr></thead>
          <tbody>
            <tr v-for="(r, i) in rows.slice(0, 20)" :key="i">
              <td v-for="c in cols" :key="c">{{ r[c] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>
