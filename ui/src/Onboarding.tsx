import {useEffect,useState} from "react";
type Step={step:string;state:string;message:string|null};
type SetupStatus={first_run:boolean;current_step:string;ready:boolean;steps:Step[]};
const labels:Record<string,string>={ai_provider:"AI provider",data_source:"Data source",data_selection:"Discover & select",semantic_review:"Semantic review",ready:"Ready"};
export function Onboarding({onReady}:{onReady:()=>void}){
 const [status,setStatus]=useState<SetupStatus|null>(null);
 const [error,setError]=useState("");
 const [busy,setBusy]=useState(false);
 const [provider,setProvider]=useState("gemini");
 const [model,setModel]=useState("");
 const [apiKey,setApiKey]=useState("");
 const [db,setDb]=useState({name:"My Database",host:"host.docker.internal",port:5432,database:"postgres",username:"postgres",password:"",sslmode:"prefer"});
 const [dbTested,setDbTested]=useState(false);
 async function refresh(){
  const response=await fetch("/api/setup/status");
  if(!response.ok)throw new Error("Unable to load setup status. Check the Data Pilot API.");
  const next:SetupStatus=await response.json();setStatus(next);if(next.ready)onReady();
 }
 useEffect(()=>{refresh().catch(e=>setError(String(e.message||e)))},[]);
 async function validateProvider(e:React.FormEvent){
  e.preventDefault();setBusy(true);setError("");
  try{
   const response=await fetch("/api/setup/ai-provider",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider,model,api_key:apiKey})});
   if(!response.ok)throw new Error(response.status===422?"Provider validation failed. Check the model, key, and provider access.":"Unable to save provider configuration.");
   setApiKey("");await refresh();
  }catch(e:any){setError(e.message||"Provider validation failed")}
  finally{setBusy(false)}
 }
 async function testDatabase(e:React.FormEvent){
  e.preventDefault();setBusy(true);setError("");setDbTested(false);
  try{
   const response=await fetch("/api/setup/data-source/test",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(db)});
   if(!response.ok)throw new Error("Connection failed. Check host, port, credentials, network and SSL.");
   setDbTested(true);
  }catch(e:any){setError(e.message||"Connection failed")}
  finally{setBusy(false)}
 }
 async function saveDatabase(){
  setBusy(true);setError("");
  try{
   const response=await fetch("/api/setup/data-source",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(db)});
   if(!response.ok)throw new Error(response.status===422?"Connection validation failed. Please test again.":"Unable to save the database connection.");
   setDb(v=>({...v,password:""}));setDbTested(false);await refresh();
  }catch(e:any){setError(e.message||"Unable to save database")}
  finally{setBusy(false)}
 }
 return <div className="onboardingPage"><div className="onboardingCard">
  <div className="onboardingBrand"><span className="mark">DP</span><div><strong>Data Pilot</strong><small>Open-source analytics engine</small></div></div>
  <p className="eyebrow">FIRST-RUN SETUP</p><h1>Welcome to Data Pilot</h1>
  <p className="onboardingLead">Connect your AI provider and database, review the semantic model, then ask your first governed question.</p>
  {status&&<div className="onboardingSteps">{status.steps.filter(s=>s.step!=="ready").map((s,i)=><div key={s.step} className={"onboardingStep "+s.state}><span>{i+1}</span><div><strong>{labels[s.step]}</strong><small>{s.state.replaceAll("_"," ")}</small></div></div>)}</div>}
  {!status&&!error&&<p>Loading setup progress…</p>}
  {status?.current_step==="ai_provider"&&<form className="onboardingForm" onSubmit={validateProvider}>
   <h2>1. Configure your AI provider</h2><p>Credentials are not returned by setup read APIs.</p>
   <label>Provider<select value={provider} onChange={e=>setProvider(e.target.value)}><option value="gemini">Google Gemini</option><option value="openai">OpenAI (adapter pending)</option><option value="anthropic">Anthropic (adapter pending)</option><option value="azure_openai">Azure OpenAI (adapter pending)</option></select></label>
   <label>Model<input value={model} onChange={e=>setModel(e.target.value)} required placeholder="Enter model ID"/></label>
   <label>API key<input value={apiKey} onChange={e=>setApiKey(e.target.value)} type="password" autoComplete="off" placeholder="Provider API key"/></label>
   <button type="submit" disabled={busy||!model.trim()}>{busy?"Validating…":"Save and validate provider"}</button>
  </form>}
  {status?.current_step==="data_source"&&<form className="onboardingForm" onSubmit={testDatabase}>
   <h2>2. Connect PostgreSQL</h2><p>Test connectivity from inside the API container. For a database on your Windows host, use <code>host.docker.internal</code> instead of localhost.</p>
   {(["name","host","port","database","username","password"] as const).map(field=><label key={field}>{field==="database"?"Database":field.charAt(0).toUpperCase()+field.slice(1)}<input required type={field==="password"?"password":field==="port"?"number":"text"} autoComplete={field==="password"?"off":undefined} value={db[field]} onChange={e=>{setDb(v=>({...v,[field]:field==="port"?Number(e.target.value):e.target.value}));setDbTested(false)}}/></label>)}
   <label>SSL mode<select value={db.sslmode} onChange={e=>{setDb(v=>({...v,sslmode:e.target.value}));setDbTested(false)}}><option value="prefer">Prefer</option><option value="require">Require</option><option value="disable">Disable (local only)</option><option value="verify-full">Verify full</option></select></label>
   <button type="submit" disabled={busy}>{busy?"Testing…":"Test connection"}</button>
   {dbTested&&<div><p role="status">Connection successful. Save this connection to continue.</p><button type="button" disabled={busy} onClick={saveDatabase}>{busy?"Saving…":"Save & Continue"}</button></div>}
  </form>}
  {status&&status.current_step!=="ai_provider"&&status.current_step!=="data_source"&&!status.ready&&<div className="onboardingForm"><h2>{labels[status.current_step]||"Continue setup"}</h2><p>This onboarding action is scheduled for the next Stage C implementation. Your progress is persisted across restarts.</p><button onClick={()=>refresh().catch(e=>setError(String(e.message||e)))}>Refresh setup status</button></div>}
  {error&&<div className="onboardingError" role="alert">{error} <button type="button" onClick={()=>refresh().then(()=>setError("")).catch(e=>setError(String(e.message||e)))}>Retry</button></div>}
 </div></div>
}
