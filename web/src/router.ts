import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import DataView from './views/DataView.vue'
import ProfilesView from './views/ProfilesView.vue'
import SystemView from './views/SystemView.vue'
import TasksView from './views/TasksView.vue'
import ReviewView from './views/ReviewView.vue'
import ResultsView from './views/ResultsView.vue'
import TaskWorkspace from './views/TaskWorkspace.vue'
import TaskEvaluationView from './views/TaskEvaluationView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/profiles' },
    { path: '/login', component: LoginView },
    { path: '/profiles', component: ProfilesView, meta: { navStep: 1 } },
    { path: '/tasks', component: TasksView, meta: { navStep: 2 } },
    { path: '/review', component: ReviewView, meta: { navStep: 3 } },
    { path: '/results', component: ResultsView, meta: { navStep: 4 } },
    { path: '/tasks/new', component: TaskWorkspace, meta: { navStep: 1, workspace: true } },
    { path: '/tasks/workspace', component: TaskWorkspace, meta: { navStep: 1, workspace: true } },
    { path: '/tasks/:taskId/evaluation', component: TaskEvaluationView, meta: { navStep: 4 } },
    { path: '/tasks/:taskId', component: TaskWorkspace, meta: { navStep: 2, workspace: true } },
    { path: '/data', component: DataView },
    { path: '/system', component: SystemView },
  ],
})
