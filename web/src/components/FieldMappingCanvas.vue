<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

type ColumnInfo = { header: string; business_hint?: string | null }
type FieldSide = { fields: string[]; combine: 'concat' | 'coalesce' | 'best_of'; separator: string; pipeline: Array<Record<string, unknown>> }
type Rule = { id: string; source: FieldSide; target: FieldSide; matcher: string; weight: number; critical: boolean; matcher_options: Record<string, unknown> }
type LinePosition = { id: string; ruleId: string; x1: number; y1: number; x2: number; y2: number }

const props = defineProps<{
  sourceColumns: ColumnInfo[]
  targetColumns: ColumnInfo[]
  rules: Rule[]
  sourceIdColumn: string
  groupCodeColumn: string
  pendingSource: string | null
}>()
const emit = defineEmits<{
  sourceClick: [header: string]
  targetClick: [header: string]
}>()

const viewMode = ref<'all' | 'connected'>('all')
const canvasRef = ref<HTMLElement | null>(null)
const chipRefs: Record<string, HTMLElement | null> = {}
const linePositions = ref<LinePosition[]>([])
const canvasSize = ref({ width: 0, height: 0 })

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))]
}

const connectedSourceHeaders = computed(() => unique(props.rules.flatMap(rule => rule.source.fields)))
const connectedTargetHeaders = computed(() => unique(props.rules.flatMap(rule => rule.target.fields)))
const connectedSourceRank = computed(() => new Map(connectedSourceHeaders.value.map((header, index) => [header, index])))

const visibleSourceColumns = computed(() => {
  if (viewMode.value === 'all') return props.sourceColumns
  const byHeader = new Map(props.sourceColumns.map(column => [column.header, column]))
  return connectedSourceHeaders.value.map(header => byHeader.get(header)).filter((column): column is ColumnInfo => Boolean(column))
})

const visibleTargetColumns = computed(() => {
  if (viewMode.value === 'all') return props.targetColumns
  const byHeader = new Map(props.targetColumns.map(column => [column.header, column]))
  const ranks = new Map<string, number[]>()
  for (const rule of props.rules) {
    const sourceRanks = rule.source.fields
      .map(field => connectedSourceRank.value.get(field))
      .filter((rank): rank is number => rank !== undefined)
    const average = sourceRanks.length ? sourceRanks.reduce((sum, rank) => sum + rank, 0) / sourceRanks.length : Number.MAX_SAFE_INTEGER
    for (const field of rule.target.fields) {
      const values = ranks.get(field) ?? []
      values.push(average)
      ranks.set(field, values)
    }
  }
  return connectedTargetHeaders.value
    .map((header, index) => ({ header, index, rank: (ranks.get(header) ?? [Number.MAX_SAFE_INTEGER]).reduce((sum, value) => sum + value, 0) / (ranks.get(header)?.length ?? 1) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map(item => byHeader.get(item.header))
    .filter((column): column is ColumnInfo => Boolean(column))
})

const hasConnectedFields = computed(() => visibleSourceColumns.value.length > 0 && visibleTargetColumns.value.length > 0)
const criticalRuleIds = computed(() => new Set(props.rules.filter(rule => rule.critical).map(rule => rule.id)))

function setChipRef(side: 's' | 't', header: string, el: unknown): void {
  chipRefs[`${side}:${header}`] = (el as HTMLElement | null) ?? null
}

function stableLineId(ruleId: string, sourceField: string, targetField: string): string {
  return `${ruleId}:${encodeURIComponent(sourceField)}:${encodeURIComponent(targetField)}`
}

function updateLines(): void {
  const canvas = canvasRef.value
  if (!canvas) {
    linePositions.value = []
    canvasSize.value = { width: 0, height: 0 }
    return
  }
  const box = canvas.getBoundingClientRect()
  const scrollLeft = canvas.scrollLeft
  const scrollTop = canvas.scrollTop
  const positions: LinePosition[] = []
  for (const rule of props.rules) {
    for (const sourceField of unique(rule.source.fields)) {
      for (const targetField of unique(rule.target.fields)) {
        const sourceElement = chipRefs[`s:${sourceField}`]
        const targetElement = chipRefs[`t:${targetField}`]
        if (!sourceElement || !targetElement) continue
        const sourceBox = sourceElement.getBoundingClientRect()
        const targetBox = targetElement.getBoundingClientRect()
        positions.push({
          id: stableLineId(rule.id, sourceField, targetField),
          ruleId: rule.id,
          x1: sourceBox.right - box.left + scrollLeft,
          y1: sourceBox.top + sourceBox.height / 2 - box.top + scrollTop,
          x2: targetBox.left - box.left + scrollLeft,
          y2: targetBox.top + targetBox.height / 2 - box.top + scrollTop,
        })
      }
    }
  }
  linePositions.value = positions
  canvasSize.value = {
    width: Math.max(canvas.scrollWidth, canvas.clientWidth),
    height: Math.max(canvas.scrollHeight, canvas.clientHeight),
  }
}

function scheduleLineUpdate(): void {
  void nextTick(updateLines)
}

function linePath(line: LinePosition): string {
  const distance = Math.max(72, line.x2 - line.x1)
  const bend = Math.max(34, distance * 0.44)
  return `M ${line.x1} ${line.y1} C ${line.x1 + bend} ${line.y1}, ${line.x2 - bend} ${line.y2}, ${line.x2} ${line.y2}`
}

watch(() => props.rules, scheduleLineUpdate, { deep: true })
watch(() => [props.sourceColumns, props.targetColumns], scheduleLineUpdate, { deep: true })
watch(viewMode, scheduleLineUpdate)

onMounted(() => {
  window.addEventListener('resize', updateLines)
  scheduleLineUpdate()
})
onBeforeUnmount(() => window.removeEventListener('resize', updateLines))
</script>

<template>
  <div class="mapping-view-tools">
    <span>字段显示</span>
    <el-radio-group v-model="viewMode" size="small">
      <el-radio-button value="all">全部字段</el-radio-button>
      <el-radio-button value="connected">仅看已连接</el-radio-button>
    </el-radio-group>
    <span v-if="viewMode === 'connected'" class="mapping-view-count">{{ linePositions.length }} 条连线</span>
  </div>
  <div v-if="viewMode === 'connected' && !hasConnectedFields" class="mapping-connected-empty">还没有字段连线，切换到“全部字段”后可开始映射。</div>
  <div v-else ref="canvasRef" class="mapping-canvas mapping-canvas-scroll" @scroll="updateLines">
    <svg class="lines" :width="canvasSize.width" :height="canvasSize.height" :style="{ width: `${canvasSize.width}px`, height: `${canvasSize.height}px` }">
      <path
        v-for="line in linePositions"
        :key="line.id"
        :d="linePath(line)"
        class="map-line"
        :class="{ critical: criticalRuleIds.has(line.ruleId) }"
      />
    </svg>
    <div class="field-col">
      <div class="field-col-title">源字段(SAP)</div>
      <div
        v-for="column in visibleSourceColumns"
        :key="`s:${column.header}`"
        :ref="el => setChipRef('s', column.header, el)"
        class="field-chip"
        :class="{
          selected: pendingSource === column.header,
          used: connectedSourceHeaders.includes(column.header),
          idcol: column.header === sourceIdColumn,
        }"
        @click="column.header !== sourceIdColumn && emit('sourceClick', column.header)"
      >
        <span>{{ column.header }}</span><em v-if="column.business_hint" class="hint">{{ column.business_hint }}</em>
      </div>
    </div>
    <div class="field-col">
      <div class="field-col-title">目标字段(集团码)</div>
      <div
        v-for="column in visibleTargetColumns"
        :key="`t:${column.header}`"
        :ref="el => setChipRef('t', column.header, el)"
        class="field-chip right"
        :class="{
          used: connectedTargetHeaders.includes(column.header),
          idcol: column.header === groupCodeColumn,
        }"
        @click="column.header !== groupCodeColumn && emit('targetClick', column.header)"
      >
        <span>{{ column.header }}</span><em v-if="column.business_hint" class="hint">{{ column.business_hint }}</em>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mapping-view-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin: 8px 0 10px;
  color: var(--mm-muted);
  font-size: 12px;
}
.mapping-view-count {
  min-width: 64px;
  text-align: right;
}
.mapping-connected-empty {
  margin: 10px 0 6px;
  padding: 20px;
  border: 1px dashed var(--mm-line);
  border-radius: 10px;
  color: var(--mm-muted);
  text-align: center;
  font-size: 12.5px;
}
.mapping-canvas.mapping-canvas-scroll {
  max-height: 460px;
  overflow: auto;
  align-items: start;
  scrollbar-gutter: stable;
  overscroll-behavior: contain;
}
.mapping-canvas.mapping-canvas-scroll .lines {
  top: 0;
  left: 0;
  right: auto;
  bottom: auto;
}
.mapping-canvas.mapping-canvas-scroll .field-col {
  max-height: none;
  overflow: visible;
}
.mapping-canvas.mapping-canvas-scroll .field-col-title {
  z-index: 3;
}
.map-line {
  vector-effect: non-scaling-stroke;
}
</style>
