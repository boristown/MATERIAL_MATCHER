import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import DataView from './views/DataView.vue'
import ProfilesView from './views/ProfilesView.vue'
import SystemView from './views/SystemView.vue'
import TasksView from './views/TasksView.vue'
import TaskWorkspace from './views/TaskWorkspace.vue'
import TaskEvaluationView from './views/TaskEvaluationView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/profiles' },
    { path: '/login', component: LoginView },
    { path: '/profiles', component: ProfilesView },
    { path: '/tasks', component: TasksView },
    { path: '/review', component: TasksView, props: { mode: 'review' } },
    { path: '/results', component: TasksView, props: { mode: 'result' } },
    { path: '/tasks/new', component: TaskWorkspace },
    { path: '/tasks/workspace', component: TaskWorkspace },
    { path: '/tasks/:taskId/evaluation', component: TaskEvaluationView },
    { path: '/tasks/:taskId', component: TaskWorkspace },
    { path: '/data', component: DataView },
    { path: '/system', component: SystemView },
  ],
})
