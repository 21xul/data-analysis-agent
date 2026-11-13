<script setup>
import { computed } from 'vue'

const props = defineProps({ chart: { type: Object, default: null } })

const geom = computed(() => {
  const c = props.chart
  if (!c || !Array.isArray(c.values) || !c.values.length) return null
  const values = c.values.map(v => Number(v) || 0)
  const labels = (c.labels || values.map((_, i) => String(i + 1))).map(String)
  const max = Math.max(...values.map(Math.abs), 1)
  const W = 480, H = 170, pad = 28
  const step = values.length > 1 ? (W - pad * 2) / (values.length - 1) : 0
  const pts = values.map((v, i) => ({ x: pad + i * step, y: H - pad - (v / max) * (H - pad * 2) }))
  return {
    W, H, pad, pts, labels, max,
    line: pts.map(p => `${p.x},${p.y}`).join(' '),
    bars: pts.map((p, i) => ({ x: p.x - Math.min(14, step / 3 || 10), y: p.y,
      w: Math.min(28, step / 1.6 || 20), h: H - pad - p.y, label: labels[i], v: values[i] }))
  }
})
</script>

<template>
  <div v-if="geom" class="chart-card">
    <div class="chart-title">{{ chart.title || '图表' }}</div>
    <svg :viewBox="`0 0 ${geom.W} ${geom.H}`" class="chart-svg" preserveAspectRatio="xMidYMid meet">
      <line :x1="geom.pad" :y1="geom.H - geom.pad" :x2="geom.W - geom.pad" :y2="geom.H - geom.pad" class="axis" />
      <template v-if="chart.type === 'bar'">
        <rect v-for="(b, i) in geom.bars" :key="i" :x="b.x" :y="b.y" :width="b.w" :height="Math.max(b.h, 1)" class="bar" />
      </template>
      <template v-else>
        <polyline :points="geom.line" class="line" />
        <circle v-for="(p, i) in geom.pts" :key="i" :cx="p.x" :cy="p.y" r="2.8" class="dot" />
      </template>
      <text v-for="(l, i) in geom.labels" :key="'l' + i" :x="geom.pts[i].x" :y="geom.H - 8"
            text-anchor="middle" class="tick">{{ l.length > 7 ? l.slice(5) : l }}</text>
    </svg>
  </div>
</template>
