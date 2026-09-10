import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/containers' },
  { path: '/containers', name: 'containers', component: () => import('../views/ContainersView.vue') },
  { path: '/images', name: 'images', component: () => import('../views/ImagesView.vue') },
  { path: '/networks', name: 'networks', component: () => import('../views/NetworksView.vue') },
  { path: '/volumes', name: 'volumes', component: () => import('../views/VolumesView.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})