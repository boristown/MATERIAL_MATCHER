<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

type VectorStatus = {
  embedding: {
    provider: string; model_id: string; dimensions: number; max_length: number; precision: string; model_dir: string;
    runtime_installed: boolean; model_installed: boolean; ready: boolean; batch_size?: number; token_budget?: number
  }
  indexes: { counts: Record<string, number>; latest: any | null; index_dir: string }
  cache_dir: string
}

const info = ref<any>(null)
const vector = ref<VectorStatus | null>(null)
const indexes = ref<any[]>([])
const benchmarks = ref<any[]>([])
const loading = ref(false)
const embeddingBusy = ref(false)
const vectorBusy = ref(false)

const readyText = computed(() => vector.value?.embedding.ready ? '已就绪' : '未就绪')

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const [infoResponse, vectorResponse, indexResponse, benchmarkResponse] = await Promise.all([
      api.get('/system/info'), api.get('/system/vector-status'), api.get('/indexes'), api.get('/system/benchmarks'),
    ])
    info.value = infoResponse.data
    vector.value = vectorResponse.data
    indexes.value = indexResponse.data.items ?? []
    benchmarks.value = benchmarkResponse.data ?? []
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function runEmbeddingBenchmark(): Promise<void> {
  embeddingBusy.value = true
  try {
    const response = await api.post('/system/benchmarks/embedding', { sample_count: 1000 })
    const profile = response.data.metrics.token_length_profile
    ElMessage.success(`Embedding：${response.data.metrics.throughput_rows_per_second} 条/秒，建议 max_length=${profile?.recommended_max_length ?? '-'}`)
    await refresh()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    embeddingBusy.value = false
  }
}

async function runVectorBenchmark(): Promise<void> {
  vectorBusy.value = true
  try {
    const response = await api.post('/system/benchmarks/vector', { target_rows: 10000, query_count: 100, dimensions: 128, top_k: 50 })
    ElMessage.success(`BBQ 内核基准完成：${response.data.metrics.search_queries_per_second} 查询/秒`)
    await refresh()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    vectorBusy.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div>
    <div class="toolbar">
      <div><h2>系统设置</h2><p>查看运行环境、Embedding 模型、向量索引和性能基准状态。</p></div>
      <el-button :loading="loading" @click="refresh">刷新状态</el-button>
    </div>

    <div class="panel" v-loading="loading">
      <h3>运行环境</h3>
      <el-descriptions v-if="info" :column="2" border>
        <el-descriptions-item label="版本">{{ info.version }}</el-descriptions-item>
        <el-descriptions-item label="数据目录">{{ info.data_dir }}</el-descriptions-item>
        <el-descriptions-item label="扫描安全上限">{{ info.baseline_max_target_rows }} Target</el-descriptions-item>
        <el-descriptions-item label="向量索引目录">{{ info.index_dir }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <div class="panel">
      <div class="section-head"><h3>Embedding Provider</h3><el-tag :type="vector?.embedding.ready ? 'success' : 'warning'">{{ readyText }}</el-tag></div>
      <el-descriptions v-if="vector" :column="2" border>
        <el-descriptions-item label="Provider">{{ vector.embedding.provider }}</el-descriptions-item>
        <el-descriptions-item label="模型">{{ vector.embedding.model_id }}</el-descriptions-item>
        <el-descriptions-item label="维度">{{ vector.embedding.dimensions }}</el-descriptions-item>
        <el-descriptions-item label="最大长度">{{ vector.embedding.max_length }}</el-descriptions-item>
        <el-descriptions-item label="最大 Batch">{{ vector.embedding.batch_size ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="Token Budget">{{ vector.embedding.token_budget ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="精度">{{ vector.embedding.precision }}</el-descriptions-item>
        <el-descriptions-item label="Runtime">{{ vector.embedding.runtime_installed ? '已安装' : '未安装' }}</el-descriptions-item>
        <el-descriptions-item label="模型文件">{{ vector.embedding.model_installed ? '已安装' : '未安装' }}</el-descriptions-item>
        <el-descriptions-item label="模型目录">{{ vector.embedding.model_dir }}</el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="vector && !vector.embedding.ready" title="向量核心已安装，但正式语义匹配需要离线安装 ONNX Runtime、tokenizers 和 bge-base-zh-v1.5 模型文件。系统不会使用测试向量冒充生产模型。" type="warning" :closable="false"/>
      <el-alert v-else-if="vector" title="正式 Embedding 基准会统计 token P50/P95/P99/P99.9、不同 max_length 截断率和 padding efficiency，用于现场选择 128/192/256/512，而不是固定拍脑袋。" type="info" :closable="false"/>
      <div class="actions"><el-button :loading="embeddingBusy" :disabled="!vector?.embedding.ready" @click="runEmbeddingBenchmark">运行正式 Embedding 基准</el-button><el-button :loading="vectorBusy" @click="runVectorBenchmark">运行 BBQ 内核基准</el-button></div>
    </div>

    <div class="panel">
      <h3>向量索引版本</h3>
      <div v-if="vector" class="stats"><span>READY {{ vector.indexes.counts.READY || 0 }}</span><span>BUILDING {{ vector.indexes.counts.BUILDING || 0 }}</span><span>FAILED {{ vector.indexes.counts.FAILED || 0 }}</span></div>
      <el-table :data="indexes" size="small" empty-text="尚未构建向量索引">
        <el-table-column prop="index_id" label="Index ID" min-width="220" show-overflow-tooltip/>
        <el-table-column prop="catalog_version_id" label="Catalog Version" min-width="180" show-overflow-tooltip/>
        <el-table-column prop="status" label="状态" width="110"/>
        <el-table-column prop="created_at" label="创建时间" min-width="180"/>
        <el-table-column label="行数" width="100"><template #default="scope">{{ scope.row.metadata?.stats?.row_count ?? scope.row.metadata?.index_metadata?.row_count ?? '-' }}</template></el-table-column>
        <el-table-column label="模型" min-width="180"><template #default="scope">{{ scope.row.metadata?.provider?.model_id ?? '-' }}</template></el-table-column>
      </el-table>
    </div>

    <div class="panel">
      <h3>性能基准记录</h3>
      <p class="muted">Embedding 基准使用正式已安装模型；BBQ 内核基准使用确定性测试向量，仅测索引/检索内核，不作为生产模型端到端性能承诺。</p>
      <el-table :data="benchmarks" size="small" empty-text="尚无基准记录">
        <el-table-column prop="kind" label="类型" width="140"/>
        <el-table-column prop="status" label="状态" width="100"/>
        <el-table-column prop="started_at" label="时间" min-width="180"/>
        <el-table-column label="吞吐" min-width="160"><template #default="scope"><span v-if="scope.row.kind==='embedding'">{{ scope.row.metrics?.throughput_rows_per_second ?? '-' }} 条/秒</span><span v-else>{{ scope.row.metrics?.search_queries_per_second ?? '-' }} 查询/秒</span></template></el-table-column>
        <el-table-column label="Token P99 / 建议长度" min-width="180"><template #default="scope"><span v-if="scope.row.kind==='embedding'">P99 {{ scope.row.metrics?.token_length_profile?.p99 ?? '-' }} / {{ scope.row.metrics?.token_length_profile?.recommended_max_length ?? '-' }}</span><span v-else>-</span></template></el-table-column>
        <el-table-column label="Padding效率" width="120"><template #default="scope"><span v-if="scope.row.kind==='embedding' && scope.row.metrics?.padding_efficiency != null">{{ (scope.row.metrics.padding_efficiency*100).toFixed(1) }}%</span><span v-else>-</span></template></el-table-column>
        <el-table-column label="预计/范围" min-width="200"><template #default="scope"><span v-if="scope.row.kind==='embedding'">110万条约 {{ scope.row.metrics?.projected_1_100_000_rows_hours ?? '-' }} 小时</span><span v-else>synthetic vector kernel</span></template></el-table-column>
        <el-table-column prop="error_message" label="错误" min-width="220" show-overflow-tooltip/>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.section-head{display:flex;justify-content:space-between;align-items:center}.stats{display:flex;gap:24px;margin:12px 0}.panel .el-alert{margin-top:14px}
</style>
