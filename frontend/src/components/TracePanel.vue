<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({ events: { type: Array, default: () => [] } })
const box = ref(null)

const labels = {
  meta: '会话', rag: 'RAG 检索', thought: '思考', action: '行动',
  observation: '观察', guardrail: '护栏', notice: '提示', final: '结论', error: '错误'
}

const icons = computed(() => props.events.map(e => labels[e.type] || e.type))

watch(() => props.events.length, async () => {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
})

function brief(ev) {
  const d = ev.data || {}
  if (ev.type === 'thought') return d.text
  if (ev.type === 'action') return `${d.tool} · ${d.arguments}`
  if (ev.type === 'observation') return `${d.ref} · ${d.tool} · ${(d.result?.facts || []).join(' ')}`
  if (ev.type === 'rag') return (d.hits || []).map(h => h.title).join('、') || '未命中'
  if (ev.type === 'meta') return `${d.mode} 模式 · ${(d.tools || []).length} 个工具`
  if (ev.type === 'final') return `${(d.conclusions || []).length} 条结论 · ${d.elapsed_ms} ms`
  if (ev.type === 'guardrail') return d.message || '工具调用被拦截'
  return d.message || d.reason || JSON.stringify(d).slice(0, 160)
}
</script>

<template>
  <section class="panel trace">
    <header class="panel-head">
      <h2>ReAct 推理轨迹</h2>
      <span class="badge">{{ events.length }} 事件</span>
    </header>
    <div class="trace-body" ref="box">
      <p v-if="!events.length" class="muted">提问后，这里会逐步显示 思考 → 行动 → 观察 的全过程。</p>
      <div v-for="(ev, i) in events" :key="ev.id || i" class="trace-item" :class="'t-' + ev.type">
        <div class="trace-tag">{{ icons[i] }}</div>
        <div class="trace-text">{{ brief(ev) }}</div>
      </div>
    </div>
  </section>
</template>
