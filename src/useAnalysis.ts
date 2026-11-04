import {useEffect, useRef, useState} from 'react';
export type Observation={id:string;label:string;severity:'low'|'medium'|'high';description:string;recommendation:string;source:string};
export type AnalysisReport={summary:string;observations:Observation[];limitations:string[];disclaimer:string;model:string;field:string;crop:string;date:string;images_analyzed:number;files_processed:number;mode:'openai'};
type Job={id:string;status:'queued'|'processing'|'completed'|'failed';progress:number;stage:string;report:AnalysisReport|null;error:string|null};
export function useAnalysis(){
 const [job,setJob]=useState<Job|null>(null),[error,setError]=useState(''),[uploading,setUploading]=useState(false),[configured,setConfigured]=useState<boolean|null>(null);
 const controller=useRef<AbortController|null>(null);
 useEffect(()=>{const abort=new AbortController();fetch('/api/health',{signal:abort.signal}).then(r=>r.ok?r.json():null).then(data=>setConfigured(data?!!data.configured:false)).catch(()=>{if(!abort.signal.aborted)setConfigured(false)});return()=>{abort.abort();controller.current?.abort()}},[]);
 const start=async(files:File[],field:string,crop:string,date:string)=>{
  controller.current?.abort();const abort=new AbortController();controller.current=abort;setJob(null);setError('');setUploading(true);
  try{
   const data=new FormData();files.forEach(f=>data.append('files',f));data.append('field',field);data.append('crop',crop);data.append('date',date);
   const res=await fetch('/api/analyses',{method:'POST',body:data,signal:abort.signal});
   if(!res.ok){let message='Не удалось начать анализ. Проверьте доступность сервиса.';try{const body=await res.json();if(typeof body.detail==='string')message=body.detail}catch{}throw Error(message)}
   let current:Job=await res.json();setConfigured(true);setJob(current);setUploading(false);
   while(current.status==='queued'||current.status==='processing'){
    await new Promise<void>((resolve,reject)=>{const onAbort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'))};const timer=setTimeout(()=>{abort.signal.removeEventListener('abort',onAbort);resolve()},900);abort.signal.addEventListener('abort',onAbort,{once:true});if(abort.signal.aborted)onAbort()});
    const response=await fetch('/api/analyses/'+encodeURIComponent(current.id),{signal:abort.signal});if(!response.ok)throw Error('Не удалось получить результат. Попробуйте повторить обследование.');current=await response.json();setJob(current);
   }
   if(current.status==='failed')throw Error(current.error||'Не удалось обработать материалы. Попробуйте другие файлы.');
  }catch(e){if(!abort.signal.aborted)setError(e instanceof Error?e.message:'Сервис анализа недоступен.')}
  finally{if(!abort.signal.aborted)setUploading(false)}
 };
 const reset=()=>{controller.current?.abort();setJob(null);setError('');setUploading(false)};
 return {job,error,configured,start,reset,uploading,busy:uploading||job?.status==='queued'||job?.status==='processing'};
}
