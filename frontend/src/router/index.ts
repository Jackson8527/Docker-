import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/containers' },
  {
    path: '/containers',
    name: 'containers',
    component: () => import('../views/ContainersView.vue'),
    meta: { title: '容器', desc: '启动、停止、查看日志、进入终端、拷贝文件、打包镜像' },
  },
  {
    path: '/images',
    name: 'images',
    component: () => import('../views/ImagesView.vue'),
    meta: { title: '镜像', desc: '拉取、删除镜像，导出为 tar 文件' },
  },
  {
    path: '/networks',
    name: 'networks',
    component: () => import('../views/NetworksView.vue'),
    meta: { title: '网络', desc: '查看与创建 Docker 网络' },
  },
  {
    path: '/volumes',
    name: 'volumes',
    component: () => import('../views/VolumesView.vue'),
    meta: { title: '卷', desc: '查看与创建数据卷' },
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
