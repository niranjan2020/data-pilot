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
 const [catalog,setCatalog]=useState<{schema_name:string;table_name:string;columns:{name:string;is_primary_key:boolean}[]}[]>([]);
 const [selected,setSelected]=useState<string[]>([]);
 const [schemaFilter,setSchemaFilter]=useState("all");

 type SemanticProposal={schema_name:string;table_name:string;suggested_name:string;description:string;key_columns:string[];attributes:string[];provenance:string;status:string;warnings:string[]};
 const [proposals,setProposals]=useState<SemanticProposal[]>([]);
 const [proposalError,setProposalError]=useState("");
 const [savedSourceId,setSavedSourceId]=useState<number|null>(null);
 const [savedSources,setSavedSources]=useState<{id:number;name:string;provider:string}[]>([]);
 const [candidateId,setCandidateId]=useState<number|null>(null);
 const [discovery,setDiscovery]=useState<{schemas:string[];tables:number}|null>(null);
 async function refresh(){
  const response=await fetch("/api/setup/status");
  if(!response.ok)throw new Error("Unable to load setup status. Check the Data Pilot API.");
  const next:SetupStatus=await response.json();setStatus(next);if(next.ready)onReady();
 }
 useEffect(()=>{refresh().catch(e=>setError(String(e.message||e)))},[]);
 useEffect(()=>{
  if(!["data_selection","semantic_review"].includes(status?.current_step||"")||savedSourceId!==null)return;
  fetch("/api/setup/data-source/active").then(async response=>{
   if(!response.ok)throw new Error("No saved datasource found. Please check your setup.");
   const source=await response.json();setSavedSourceId(source.id);
  }).catch(async ()=>{
   try{
    const response=await fetch("/api/setup/data-sources");
    if(!response.ok)throw new Error("Unable to list saved databases.");
    const sources=await response.json();setSavedSources(sources);
    if(sources.length)setCandidateId(sources[0].id);
    else setError("No saved databases found. Please reconnect your database.");
   }catch(e:any){setError(e.message||"Unable to restore saved databases")}
  });
 },[status?.current_step,savedSourceId]);
 useEffect(()=>{
  if(status?.current_step==="data_selection"&&savedSourceId!==null){
   loadDatasets(savedSourceId).catch(()=>{});
  }
 },[status?.current_step,savedSourceId]);


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
   const saved=await response.json();setSavedSourceId(saved.id);
   setDb(v=>({...v,password:""}));setDbTested(false);await refresh();
  }catch(e:any){setError(e.message||"Unable to save database")}
  finally{setBusy(false)}
 }
 async function activateSavedDatabase(){
  if(candidateId===null)return;
  setBusy(true);setError("");
  try{
   const response=await fetch("/api/setup/data-source/"+candidateId+"/activate",{method:"POST"});
   if(!response.ok)throw new Error("Saved database connection unavailable. Verify the database is running and its stored credentials are valid.");
   setSavedSourceId(candidateId);await refresh();
  }catch(e:any){setError(e.message||"Unable to activate saved database")}
  finally{setBusy(false)}
 }
 const datasetKey=(schema:string,table:string)=>JSON.stringify([schema,table]);
 async function loadDatasets(sourceId:number){
  const response=await fetch("/api/setup/data-source/"+sourceId+"/datasets");
  if(!response.ok)throw new Error("Unable to load discovered datasets.");
  const data=await response.json();
  setCatalog(data.datasets);
  setSelected(data.selected.map((s:{schema_name:string;table_name:string})=>datasetKey(s.schema_name,s.table_name)));
 }
 async function loadProposals(sourceId:number){
  setProposalError("");
  const response=await fetch("/api/setup/data-source/"+sourceId+"/semantic-proposals");
  if(!response.ok)throw new Error("Unable to load semantic drafts from approved datasets.");
  setProposals(await response.json());
 }
 useEffect(()=>{
  if(status?.current_step==="semantic_review"&&savedSourceId!==null){
   loadProposals(savedSourceId).catch(e=>setProposalError(String(e.message||e)));
  }
 },[status?.current_step,savedSourceId]);
 async function approveDatasets(){
  if(savedSourceId===null||selected.length===0)return;
  setBusy(true);setError("");
  try{
   const datasets=selected.map(key=>{const [schema_name,table_name]=JSON.parse(key);return {schema_name,table_name}});
   const response=await fetch("/api/setup/data-source/"+savedSourceId+"/datasets",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({datasets})});
   if(!response.ok)throw new Error("Unable to save dataset selection.");
   await refresh();
  }catch(e:any){setError(e.message||"Selection failed")}
  finally{setBusy(false)}
 }
 async function discoverSavedDatabase(){
  if(savedSourceId===null)return;
  setBusy(true);setError("");
  try{
   const response=await fetch("/api/setup/data-source/"+savedSourceId+"/discover",{method:"POST"});
   if(!response.ok)throw new Error("Discovery failed. Check the saved database connection.");
   setDiscovery(await response.json());await loadDatasets(savedSourceId);
  }catch(e:any){setError(e.message||"Discovery failed")}
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
  {status?.current_step==="data_selection"&&<div className="onboardingForm"><h2>3. Discover & select</h2><p>Discover the saved database without entering credentials again. Dataset approval will follow.</p>{savedSourceId!==null?<button disabled={busy} onClick={discoverSavedDatabase}>{busy?"Discovering…":"Discover saved database"}</button>:<div><p>Select the saved database to continue without re-entering credentials.</p>{savedSources.length>0?<><label>Saved database<select value={candidateId??""} onChange={e=>setCandidateId(Number(e.target.value))}>{savedSources.map(s=><option key={s.id} value={s.id}>{s.name} ({s.provider})</option>)}</select></label><button disabled={busy||candidateId===null} onClick={activateSavedDatabase}>{busy?"Connecting…":"Use saved database"}</button></>:<p>Checking saved database connections…</p>}</div>}{discovery&&<p role="status">Discovered {discovery.tables} tables across {discovery.schemas.length} schemas.</p>}
 {catalog.length>0&&<div style={{marginTop:20}}><h3>Select datasets ({selected.length} selected)</h3>
 <p>Choose only the tables needed for your first questions. You can expand the selection later.</p>
 <label>Schema<select value={schemaFilter} onChange={e=>setSchemaFilter(e.target.value)}><option value="all">All schemas</option>{Array.from(new Set(catalog.map(t=>t.schema_name))).sort().map(s=><option key={s} value={s}>{s}</option>)}</select></label>
 <div style={{maxHeight:300,overflowY:"auto",border:"1px solid #e4e7ec",borderRadius:8,padding:12}}>
 {catalog.filter(t=>schemaFilter==="all"||t.schema_name===schemaFilter).map(t=>{const key=datasetKey(t.schema_name,t.table_name);return <label key={key} style={{display:"flex",alignItems:"center",gap:8,margin:"7px 0"}}><input style={{width:16,margin:0}} type="checkbox" checked={selected.includes(key)} onChange={e=>setSelected(v=>e.target.checked?[...v,key]:v.filter(k=>k!==key))}/><span>{t.schema_name}.{t.table_name} <small>({t.columns.length} columns; {t.columns.filter(col=>col.is_primary_key).length} PK)</small></span></label>})}
 </div><button type="button" disabled={busy||selected.length===0} onClick={approveDatasets} style={{marginTop:15}}>{busy?"Saving…":"Approve selected datasets & continue"}</button></div>}</div>}
  {status?.current_step==="semantic_review"&&<div className="onboardingForm">
 <h2>4. Review semantic drafts</h2>
 <p>These are physical schema facts, not verified business definitions. No metric, business rule or relationship is published by this preview.</p>
 {savedSourceId===null?<p>Restoring saved datasource…</p>:<button type="button" disabled={busy} onClick={()=>loadProposals(savedSourceId).catch(e=>setProposalError(String(e.message||e)))}>Refresh proposals</button>}
 {proposalError&&<p role="alert">{proposalError}</p>}
 {proposals.map(p=><section key={datasetKey(p.schema_name,p.table_name)} style={{marginTop:16,padding:14,border:"1px solid #e4e7ec",borderRadius:8}}>
 <h3>{p.schema_name}.{p.table_name}</h3>
 <p>{p.description}</p>
 <p><strong>Suggested label:</strong> {p.suggested_name}</p>
 <p><strong>Primary keys:</strong> {p.key_columns.length?p.key_columns.join(", "):"Not discovered"}</p>
 <p><strong>Columns ({p.attributes.length}):</strong> {p.attributes.join(", ")}</p>
 <p><strong>Provenance:</strong> {p.provenance} · <strong>Status:</strong> {p.status}</p>
 {p.warnings.map(w=><p key={w} role="note">{w}</p>)}
 </section>)}
 <p>Review and approval editing will be enabled in the next C5 slice. These drafts have not been saved as authoritative semantics.</p>
 </div>}
 {status&&status.current_step!=="ai_provider"&&status.current_step!=="data_source"&&status.current_step!=="data_selection"&&status.current_step!=="semantic_review"&&!status.ready&&<div className="onboardingForm"><h2>{labels[status.current_step]||"Continue setup"}</h2><p>This onboarding action is scheduled for the next Stage C implementation. Your progress is persisted across restarts.</p><button onClick={()=>refresh().catch(e=>setError(String(e.message||e)))}>Refresh setup status</button></div>}
  {error&&<div className="onboardingError" role="alert">{error} <button type="button" onClick={()=>refresh().then(()=>setError("")).catch(e=>setError(String(e.message||e)))}>Retry</button></div>}
 </div></div>
}
