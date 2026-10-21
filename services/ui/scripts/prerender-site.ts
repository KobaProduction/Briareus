/** Keep the public page crawler-readable while using the Panel's real components. */
import {readFile,writeFile} from 'node:fs/promises'
import {createServer} from 'vite'
import {createSSRApp} from 'vue'
import {renderToString} from 'vue/server-renderer'

const server=await createServer({appType:'custom',mode:'production',server:{middlewareMode:true}})
try{
  const {default:LandingPage}=await server.ssrLoadModule('/src/pages/public/LandingPage.vue')
  const markup=await renderToString(createSSRApp(LandingPage))
  const path=new URL('../dist/site.html',import.meta.url)
  const template=await readFile(path,'utf8')
  if(!template.includes('<div id="site"></div>'))throw new Error('Public page mount point missing')
  await writeFile(path,template.replace('<div id="site"></div>',()=>`<div id="site">${markup}</div>`))
}finally{await server.close()}
