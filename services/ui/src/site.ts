import {createApp,createSSRApp} from 'vue'
import {LandingPage} from '@/pages/public'
import '@/app/styles.css'

const mount=document.getElementById('site')
if(mount)(mount.hasChildNodes()?createSSRApp:createApp)(LandingPage).mount(mount)
