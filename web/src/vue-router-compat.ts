import Vue from 'vue'
import { getCurrentInstance } from 'vue'
import type VueRouter from 'vue-router'
import VueRuntime from 'vue-router/dist/vue-router.esm'

Vue.use(VueRuntime)

const originalPush = VueRuntime.prototype.push
const originalReplace = VueRuntime.prototype.replace

VueRuntime.prototype.push = function patchedPush(this: any, to: any, onComplete?: any, onAbort?: any): any {
  if (onComplete || onAbort) return originalPush.call(this, to, onComplete, onAbort)
  return new Promise<void>((resolve) => { originalPush.call(this, to, () => resolve(), () => resolve()) })
}

VueRuntime.prototype.replace = function patchedReplace(this: any, to: any, onComplete?: any, onAbort?: any): any {
  if (onComplete || onAbort) return originalReplace.call(this, to, onComplete, onAbort)
  return new Promise<void>((resolve) => { originalReplace.call(this, to, () => resolve(), () => resolve()) })
}

export function createWebHistory(_base?: string): any {
  return { xp: 'history' }
}

export function createRouter(options: any): VueRouter {
  return new VueRuntime({ mode: 'history', routes: options.routes, scrollBehavior: options.scrollBehavior }) as VueRouter
}

export function useRouter(): VueRouter {
  const instance = getCurrentInstance()
  return ((instance ? instance.proxy : (Vue as any).prototype) as any).$router as VueRouter
}

export function useRoute(): any {
  const vm: any = (getCurrentInstance() as any).proxy
  const routeKeys = ['path', 'params', 'query', 'hash', 'fullPath', 'matched', 'meta', 'name', 'redirectedFrom']
  return new Proxy({} as any, {
    get: (_t, key) => (vm.$route ? (vm.$route as any)[key as string] : undefined),
    has: (_t, key) => routeKeys.indexOf(String(key)) >= 0,
    ownKeys: () => routeKeys,
    getOwnPropertyDescriptor: (_t, key) => ({ enumerable: true, configurable: true, value: vm.$route ? (vm.$route as any)[key as string] : undefined }),
  })
}

export default VueRuntime
