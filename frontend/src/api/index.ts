import axios from 'axios'

export interface ContainerRow {
  id: string
  name: string
  image: string
  state: string
  status: string
  ports: string
  created: string
}

export interface ImageRow {
  id: string
  tags: string[] | null
  digest?: string
}

export interface NetworkRow {
  id: string
  name: string
  driver: string
  scope: string
}

export interface VolumeRow {
  name: string
  driver: string
  mountpoint: string
}

export interface RunContainerPayload {
  image: string
  name?: string
  ports?: string
  env?: string
  volumes?: string
  command?: string
  restart_policy?: string
  auto_start: boolean
}

export interface PullResult {
  ok: boolean
  image: string
  source: string
}

const http = axios.create({ baseURL: '/api', timeout: 30000 })

// Pulling an image can legitimately take minutes, so that one call opts out
// of the client-side timeout instead of aborting mid-download.
const NO_TIMEOUT = { timeout: 0 }

export const containersApi = {
  list: (all = false) => http.get('/containers', { params: { all } }),
  create: (payload: RunContainerPayload) => http.post('/containers', payload),
  start: (id: string) => http.post(`/containers/${id}/start`),
  stop: (id: string) => http.post(`/containers/${id}/stop`),
  restart: (id: string) => http.post(`/containers/${id}/restart`),
  pause: (id: string) => http.post(`/containers/${id}/pause`),
  unpause: (id: string) => http.post(`/containers/${id}/unpause`),
  remove: (id: string, force = false) => http.delete(`/containers/${id}`, { params: { force } }),
  commit: (id: string, repo: string, tag: string) =>
    http.post(`/containers/${id}/commit`, { repo, tag }),
}

export const imagesApi = {
  list: () => http.get('/images'),
  remove: (id: string, force = false) => http.delete(`/images/${id}`, { params: { force } }),
  pull: (name: string, tag: string) => http.post('/images/pull', { name, tag }, NO_TIMEOUT),
  mirrors: () => http.get('/images/pull/mirrors'),
  saveUrl: (id: string) => `/api/images/${id}/save`,
}

export const networksApi = {
  list: () => http.get('/networks'),
  create: (name: string, driver: string) => http.post('/networks', { name, driver }),
  remove: (id: string) => http.delete(`/networks/${id}`),
}

export const volumesApi = {
  list: () => http.get('/volumes'),
  create: (name: string) => http.post('/volumes', { name }),
  remove: (id: string) => http.delete(`/volumes/${id}`),
}

export default http