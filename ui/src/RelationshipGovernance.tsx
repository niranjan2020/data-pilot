import {useEffect,useState} from "react";

type Review={from_schema:string;from_table:string;from_column:string;to_schema:string;to_table:string;to_column:string;cardinality:string;review_status:string;join_policy:string;description:string};
const key=(r:Review)=>[r.from_schema,r.from_table,r.from_column,r.to_schema,r.to_table,r.to_column].join("|");
export function RelationshipGovernance({sourceId}:{sourceId:number|null}){
 const [reviews,setReviews]=useState<Review[]>([]);
 const [grants,setGrants]=useState<Review[]>([]);
 const [selected,setSelected]=useState("");
 const [draft,setDraft]=useState<Review|null>(null);
 const [busy,setBusy]=useState(false);
 const [message,setMessage]=useState("");
 const base="/api/setup/data-source/"+sourceId;
 async function request(path:string,method?:string,payload?:Review){
  const res=await fetch(base+path,{method:method||"GET",headers:{"Content-Type":"application/json"},body:payload?JSON.stringify(payload):undefined});
  const data=await res.json();
  if(!res.ok)throw Error(typeof data.detail==="string"?data.detail:JSON.stringify(data));
  return data;
 }
 async function refresh(){
  if(sourceId===null)return;
  try{const [items,published]=await Promise.all([request("/relationship-reviews"),request("/relationship-publications")]);setReviews(items);setGrants(published);}
  catch(e){setMessage(String(e))}
 }
 useEffect(()=>{setReviews([]);setGrants([]);setSelected("");setDraft(null);setMessage("");void refresh()},[sourceId]);
 async function perform(path:string,method:string){
  if(!draft)return;
  setBusy(true);setMessage("");
  try{const result=await request(path,method,draft);setMessage(JSON.stringify(result,null,2));await refresh()}
  catch(e){setMessage(String(e))}
  finally{setBusy(false)}
 }
 if(sourceId===null)return <p>Select a saved datasource to manage its relationships.</p>;
 return <section className="grid"><article className="wide">
 <h3>Relationship governance</h3>
 <p>Review, verify against live data, and publish approved joins. The datasource ID is selected automatically.</p>
 <div className="semanticForm"><label>Relationship
 <select value={selected} onChange={e=>{const v=e.target.value;setSelected(v);setDraft(reviews.find(x=>key(x)===v)||null);setMessage("")}}>
 <option value="">Choose an existing relationship review</option>
 {reviews.map(x=><option key={key(x)} value={key(x)}>{x.from_schema}.{x.from_table}.{x.from_column} → {x.to_schema}.{x.to_table}.{x.to_column}</option>)}
 </select></label></div>
 {draft&&<><p>Publication status: <strong>{grants.some(x=>key(x)===key(draft))?"Published":"Not published"}</strong></p>
 <div className="semanticForm">
 <label>Cardinality<select value={draft.cardinality} onChange={e=>setDraft({...draft,cardinality:e.target.value})}>{["many_to_one","one_to_one","one_to_many","many_to_many","unknown"].map(x=><option key={x}>{x}</option>)}</select></label>
 <label>Review<select value={draft.review_status} onChange={e=>setDraft({...draft,review_status:e.target.value})}><option value="approved">Approved</option><option value="rejected">Rejected</option></select></label>
 <label>Join policy<select value={draft.join_policy} onChange={e=>setDraft({...draft,join_policy:e.target.value})}><option value="unconfigured">Unconfigured</option><option value="preserve_source">Preserve source (LEFT JOIN)</option><option value="matched_only">Matched only (INNER JOIN)</option></select></label>
 <label>Description<input value={draft.description||""} onChange={e=>setDraft({...draft,description:e.target.value})}/></label>
 </div>
 <div className="actions"><button disabled={busy} onClick={()=>perform("/relationship-reviews","PUT")}>1. Save review</button>
 <button disabled={busy} onClick={()=>perform("/relationship-verification","POST")}>2. Verify live data</button>
 <button disabled={busy} onClick={()=>perform("/relationship-publication","POST")}>3. Publish</button>
 <button disabled={busy} onClick={()=>refresh()}>Refresh</button></div></>}
 {!reviews.length&&<p>No reviewed relationships found. First discover and review relationship candidates in datasource onboarding.</p>}
 {message&&<pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{message}</pre>}
 </article></section>;
}
