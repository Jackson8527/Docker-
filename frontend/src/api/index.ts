import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 30000 })

export const containersApi = {
  list: (all = false) => http.get('/containers', { params: { all } }),
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
  pull: (name: string, tag: string) => http.post('/images/pull', { name, tag }),
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