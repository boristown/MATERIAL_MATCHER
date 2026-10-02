import type VueRouter from 'vue-router'
import type { Route } from 'vue-router'

declare module 'vue-router' {
  export function useRouter(): VueRouter
  export function useRoute(): Route
  export function createRouter(options: any): VueRouter
  export function createWebHistory(base?: string): any
}
