import {defineConfig, loadEnv} from 'vite';

export default defineConfig(({mode})=>{
  const env=loadEnv(mode,process.cwd(),'');
  const proxy={target:env.BACKEND_URL || 'http://127.0.0.1:8000',changeOrigin:true};
  return {server:{proxy:{'/api':proxy,'/health':proxy}},preview:{proxy:{'/api':proxy,'/health':proxy}}};
});
