<script setup lang="ts">
const props = defineProps<{ title: string }>()
</script>

<template>
  <div class="toolbar">
    <div>
      <h2>{{ props.title }}</h2>
      <p>本区按 v2.5 设计逐步实现，不增加额外一级导航。</p>
    </div>
  </div>
</template>
