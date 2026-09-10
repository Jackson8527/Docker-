import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as Icons from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import './styles/main.css'

const app = createApp(App)
app.use(ElementPlus)
for (const [name, comp] of Object.entries(Icons)) {
  app.component(name, comp)
}
app.use(router)
app.mount('#app')