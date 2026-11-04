import {useCallback,useEffect,useState} from 'react';
export function useAuth(){
 const [state,setState]=useState<{is_admin:boolean;username:string|null}>({is_admin:false,username:null});
 const [loading,setLoading]=useState(true);
 const refresh=useCallback(async()=>{try{const r=await fetch('/api/auth/me',{credentials:'same-origin'});if(!r.ok)throw Error();setState(await r.json())}catch{setState({is_admin:false,username:null})}finally{setLoading(false)}},[]);
 useEffect(()=>{void refresh();const onExpired=()=>{void refresh()};window.addEventListener('seltactor:session-expired',onExpired);return()=>window.removeEventListener('seltactor:session-expired',onExpired)},[refresh]);
 const logout=async()=>{const r=await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});if(!r.ok)throw Error('Не удалось завершить сеанс. Попробуйте снова.');setState({is_admin:false,username:null})};
 return {isAdmin:state.is_admin,username:state.username,loading,refresh,logout};
}
