import {defineConfig} from 'vite';
export default defineConfig({server:{fs:{deny:['**/.git/**','**/.env*','**/key','**/admin-credentials.txt','**/*.{crt,pem}']},proxy:{'/api':{target:'http://127.0.0.1:8000',changeOrigin:true}}}});
