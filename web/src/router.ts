import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import PlaceholderView from './views/PlaceholderView.vue'
import ProfilesView from './views/ProfilesView.vue'
import SystemView from './views/SystemView.vue'
import TasksView from './views/TasksView.vue'
import TaskWorkspace from './views/TaskWorkspace.vue'
import TaskEvaluationView from './views/TaskEvaluationView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/tasks' },
    { path: '/login', component: LoginView },
    { path: '/tasks', component: TasksView },
    { path: '/tasks/new', component: TaskWorkspace },
    { path: '/tasks/:taskId/evaluation', component: TaskEvaluationView },
    { path: '/tasks/:taskId', component: TaskWorkspace },
    { path: '/profiles', component: ProfilesView },
    { path: '/data', component: PlaceholderView, props: { title: '基础数据' } },
    { path: '/system', component: SystemView },
  ],
})
