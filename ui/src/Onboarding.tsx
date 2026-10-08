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
 type RelationshipCandidate={from_schema:string;from_table:string;from_column:string;to_schema:string;to_table:string;to_column:string;provenance:string;verified:boolean;status:string};
 const [relationships,setRelationships]=useState<RelationshipCandidate[]>([]);
 const [relationshipReviews,setRelationshipReviews]=useState<Record<string,{cardinality:string;review_status:string;description:string}>>({});
 const relationshipKey=(r:RelationshipCandidate)=>[r.from_schema,r.from_table,r.from_column,r.to_schema,r.to_table,r.to_column].join("|");
 const [relationshipSaving,setRelationshipSaving]=useState(false);
 const [relationshipError,setRelationshipError]=useState("");
 const [proposalError,setProposalError]=useState("");
 const [semanticEdits,setSemanticEdits]=useState<Record<string,{description:string;business_meaning:string;grain:string;aliases:string}>>({});
 const [approvedKeys,setApprovedKeys]=useState<string[]>([]);
 const [approvalMessage,setApprovalMessage]=useState("");
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
  const drafts:SemanticProposal[]=await response.json();
  setProposals(drafts);
  const approvedResponse=await fetch("/api/setup/data-source/"+sourceId+"/semantic-approved");
  if(!approvedResponse.ok)throw new Error("Unable to restore approved semantic definitions.");
  const approved=await approvedResponse.json();
  const edits:Record<string,{description:string;business_meaning:string;grain:string;aliases:string}>={};
  for(const p of drafts)edits[datasetKey(p.schema_name,p.table_name)]={description:p.description,business_meaning:"",grain:"",aliases:""};
  for(const a of approved)edits[datasetKey(a.schema_name,a.table_name)]={description:a.description||"",business_meaning:a.business_meaning||"",grain:a.grain||"",aliases:(a.aliases||[]).join(", ")};
  setSemanticEdits(edits);
  setApprovedKeys(approved.map((a:{schema_name:string;table_name:string})=>datasetKey(a.schema_name,a.table_name)));
  const relationshipResponse=await fetch("/api/setup/data-source/"+sourceId+"/relationship-proposals");
  if(relationshipResponse.ok){setRelationships(await relationshipResponse.json());setRelationshipError("");}
  else{setRelationshipError("Unable to load relationship candidates.");}
  const reviewsResponse=await fetch("/api/setup/data-source/"+sourceId+"/relationship-reviews");
  if(reviewsResponse.ok){const reviews=await reviewsResponse.json();const values:Record<string,{cardinality:string;review_status:string;description:string}>={};for(const review of reviews)values[relationshipKey(review)]={cardinality:review.cardinality,review_status:review.review_status,description:review.description};setRelationshipReviews(values);}


 }
 useEffect(()=>{
  if(status?.current_step==="semantic_review"&&savedSourceId!==null){
   loadProposals(savedSourceId).catch(e=>setProposalError(String(e.message||e)));
  }
 },[status?.current_step,savedSourceId]);
 async function saveRelationshipReview(rel:RelationshipCandidate,review_status:"approved"|"rejected"){
  if(savedSourceId===null)return;
  const key=relationshipKey(rel);
  const review=relationshipReviews[key]||{cardinality:"unknown",review_status:"",description:""};
  setRelationshipSaving(true);setRelationshipError("");
  try{
   const response=await fetch("/api/setup/data-source/"+savedSourceId+"/relationship-reviews",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({...rel,cardinality:review.cardinality,description:review.description,review_status})});
   if(!response.ok){const data=await response.json();throw new Error(data.detail||"Unable to save review.");}
   setRelationshipReviews(v=>({...v,[key]:{...review,review_status}}));
  }catch(e:any){setRelationshipError(e.message||"Unable to save relationship review.")}
  finally{setRelationshipSaving(false)}
 }
 async function approveSemantic(p:SemanticProposal){
  if(savedSourceId===null)return;
  const key=datasetKey(p.schema_name,p.table_name);
  const edit=semanticEdits[key];
  if(!edit?.description.trim()||!edit.business_meaning.trim()||!edit.grain.trim()){setProposalError("Description, business meaning and grain are required for approval.");return}
  setBusy(true);setProposalError("");setApprovalMessage("");
  try{
   const response=await fetch("/api/setup/data-source/"+savedSourceId+"/semantic-approved",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({schema_name:p.schema_name,table_name:p.table_name,description:edit.description,business_meaning:edit.business_meaning,grain:edit.grain,aliases:edit.aliases.split(",").map(s=>s.trim()).filter(Boolean)})});
   if(!response.ok)throw new Error("Approval failed. Check the dataset and required fields.");
   setApprovedKeys(keys=>Array.from(new Set([...keys,key])));
   setApprovalMessage(p.schema_name+"."+p.table_name+" approved. Semantic indexing is not yet enabled.");
  }catch(e:any){setProposalError(e.message||"Approval failed")}
  finally{setBusy(false)}
 }
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
 <section className="semanticDraftCard">
 <div className="semanticDraftHeader"><div><h3>Suggested relationships</h3><p>Review potential joins between your selected datasets. No relationship is published automatically.</p></div><span className="semanticDraftStatus">{relationships.length} candidates</span></div>
 {relationshipError&&<p role="alert">{relationshipError}</p>}
 {relationships.length===0?<p>No declared foreign keys or same-schema naming matches found among the selected datasets. You can still define joins during later semantic modeling.</p>:
 <div className="relationshipCandidateList">{relationships.map(rel=><div key={JSON.stringify(rel)} className="relationshipCandidate">
 <div><strong>{rel.from_schema}.{rel.from_table}.{rel.from_column}</strong><span> → </span><strong>{rel.to_schema}.{rel.to_table}.{rel.to_column}</strong></div>
 <div className="relationshipEvidence">{rel.verified?"Declared database foreign key":"Unverified column-name suggestion"} · {rel.provenance} · {relationshipReviews[relationshipKey(rel)]?.review_status||"Pending review"}</div>
 <div className="semanticDraftFields">
 <label>Join cardinality <small>From table → To table. Confirm using business knowledge and key uniqueness.</small>
 <select value={relationshipReviews[relationshipKey(rel)]?.cardinality||"unknown"} onChange={e=>setRelationshipReviews(v=>({...v,[relationshipKey(rel)]:{...v[relationshipKey(rel)],cardinality:e.target.value}}))}>
 <option value="unknown">Unknown — needs review</option><option value="many_to_one">Many to one</option><option value="one_to_many">One to many</option><option value="one_to_one">One to one</option><option value="many_to_many">Many to many</option></select></label>
 <label>Relationship meaning <small>Optional context for future semantic modeling.</small><input value={relationshipReviews[relationshipKey(rel)]?.description||""} onChange={e=>setRelationshipReviews(v=>({...v,[relationshipKey(rel)]:{...v[relationshipKey(rel)],description:e.target.value}}))} placeholder="What does this relationship represent?"/></label>
 </div>
 <div className="semanticDraftFooter"><button type="button" disabled={relationshipSaving||(relationshipReviews[relationshipKey(rel)]?.cardinality||"unknown")==="unknown"} onClick={()=>saveRelationshipReview(rel,"approved")}>Approve relationship</button><button type="button" disabled={relationshipSaving} onClick={()=>saveRelationshipReview(rel,"rejected")}>Reject</button></div>
 </div>)}</div>}
 <p>Human review decisions are saved separately. Reviewed relationships are not yet activated for SQL generation.</p>
 </section>
 {proposals.map(p=>{const key=datasetKey(p.schema_name,p.table_name);const edit=semanticEdits[key];const update=(field:"description"|"business_meaning"|"grain"|"aliases",value:string)=>setSemanticEdits(v=>({...v,[key]:{...v[key],[field]:value}}));return <section key={key} className="semanticDraftCard">
 <div className="semanticDraftHeader"><div><h3>{p.schema_name}.{p.table_name}</h3><p>{p.attributes.length} columns · Primary key: {p.key_columns.length?p.key_columns.join(", "):"not discovered"}</p></div><span className={approvedKeys.includes(key)?"semanticDraftStatus approved":"semanticDraftStatus"}>{approvedKeys.includes(key)?"Approved":"Needs review"}</span></div>
 <details className="semanticDraftDetails"><summary>View discovered columns ({p.attributes.length})</summary><div className="semanticColumnList">{p.attributes.join(", ")}</div><p>Source: {p.provenance}. Column names alone do not establish business meaning.</p></details>
 <div className="semanticDraftFields">
 <label>Table description <small>What information does this dataset contain?</small><textarea rows={3} placeholder="Describe the dataset in plain language" value={edit?.description||""} onChange={e=>update("description",e.target.value)}/></label>
 <label>Business meaning <small>How does your business interpret and use these records?</small><textarea rows={3} placeholder="Explain the meaning and important caveats" value={edit?.business_meaning||""} onChange={e=>update("business_meaning",e.target.value)}/></label>
 <label>Row grain <small>What does one row represent? Confirm before approval.</small><input placeholder="e.g. One record per unique business event" value={edit?.grain||""} onChange={e=>update("grain",e.target.value)}/></label>
 <label>Alternative names <small>Optional, separated by commas</small><input placeholder="Common business names" value={edit?.aliases||""} onChange={e=>update("aliases",e.target.value)}/></label>
 </div>
 <div className="semanticDraftFooter"><button type="button" disabled={busy||!edit?.description.trim()||!edit?.business_meaning.trim()||!edit?.grain.trim()} onClick={()=>approveSemantic(p)}>{approvedKeys.includes(key)?"Save updated definition":"Approve definition"}</button><span>Human approval · Indexing pending</span></div>
 {p.warnings.length>0&&<details className="semanticDraftDetails"><summary>Review notes ({p.warnings.length})</summary>{p.warnings.map(w=><p key={w}>{w}</p>)}</details>}
 </section>})}
 <p>Approval persists reviewed dataset definitions only. Query readiness requires subsequent semantic indexing and validation.</p>{approvalMessage&&<p role="status">{approvalMessage}</p>}
 </div>}
 {status&&status.current_step!=="ai_provider"&&status.current_step!=="data_source"&&status.current_step!=="data_selection"&&status.current_step!=="semantic_review"&&!status.ready&&<div className="onboardingForm"><h2>{labels[status.current_step]||"Continue setup"}</h2><p>This onboarding action is scheduled for the next Stage C implementation. Your progress is persisted across restarts.</p><button onClick={()=>refresh().catch(e=>setError(String(e.message||e)))}>Refresh setup status</button></div>}
  {error&&<div className="onboardingError" role="alert">{error} <button type="button" onClick={()=>refresh().then(()=>setError("")).catch(e=>setError(String(e.message||e)))}>Retry</button></div>}
 </div></div>
}
