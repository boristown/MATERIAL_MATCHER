import Vue from 'vue'
import ElementUI from 'element-ui'
import zhLocale from 'element-ui/lib/locale/lang/zh-CN'
import 'element-ui/lib/theme-chalk/index.css'
import './styles.css'
import './business-name-guard.css'
import App from './App.vue'
import { router } from './router'

Vue.use(ElementUI, { locale: zhLocale })

new Vue({
  router,
  render: (h) => h(App),
}).$mount('#app')
