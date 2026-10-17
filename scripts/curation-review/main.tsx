import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {NewsroomReferencesView} from '../../components/newsroom-references-view';
import {NewsroomOrganizerShell} from '../../components/newsroom-organizer-shell';
import {NewsroomCurationProvider} from '../../components/newsroom-curation-provider';
import type {CurationBootstrap} from '../../lib/curation-client';
import '../../app/tailwind.css';
import '../../app/globals.css';
import 'cyclotron/styles/components.css';
import './review.css';
function App(){
 const [bootstrap,setBootstrap]=useState<CurationBootstrap|null>(null),[error,setError]=useState('');
 const [account,setAccount]=useState('11111111-1111-4111-8111-111111111111'),[mode,setMode]=useState('embedded');
 async function select(nextAccount:string,nextMode:string){
  setBootstrap(null);setError('');
  try{const response=await fetch('/review/selection',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account:nextAccount,mode:nextMode})});if(!response.ok)throw new Error('Fixture selection failed');const context=await fetch('/api/newsroom/curation/context');if(!context.ok)throw new Error('Curation context unavailable');setBootstrap(await context.json());}
  catch(failure){setError(String(failure));}
 }
 useEffect(()=>{void select('11111111-1111-4111-8111-111111111111','embedded');},[]);
 return <NewsroomOrganizerShell activeTab="references" appTitle="Papyrus" backHref="/" backLabel="Local review" pageTitle="References" showNavigation={false}>
  <div className="review-toolbar"><strong>Offline integration review</strong><span>Synthetic identity, sources, model and evaluator. Native core, stores and guarded BFF are real. Remote uses an in-process HTTP peer; no hosted deployment.</span><label>Fixture account<select aria-label="Fixture account" value={account} onChange={event=>{setAccount(event.target.value);void select(event.target.value,mode);}}><option value="11111111-1111-4111-8111-111111111111">Account A</option><option value="22222222-2222-4222-8222-222222222222">Account B</option></select></label><label>Execution<select aria-label="Execution" value={mode} onChange={event=>{setMode(event.target.value);void select(account,event.target.value);}}><option value="embedded">Embedded</option><option value="remote">Remote contract</option></select></label><label>Appearance<select aria-label="Appearance" defaultValue="system" onChange={event=>{document.documentElement.classList.toggle('dark',event.target.value==='dark'||(event.target.value==='system'&&matchMedia('(prefers-color-scheme: dark)').matches));}}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label><small>URL-only example: https://example.invalid/paper or https://example.invalid/web. Choose deliberate labels; priming explanations are optional. No paid calls.</small></div>
  {error?<p role="alert">{error}</p>:null}<NewsroomCurationProvider bootstrap={bootstrap}><NewsroomReferencesView references={[]} onReview={()=>{}} /></NewsroomCurationProvider>
 </NewsroomOrganizerShell>
}
document.documentElement.classList.toggle('dark',matchMedia('(prefers-color-scheme: dark)').matches);
createRoot(document.getElementById('root')!).render(<App/>);
