import {useState} from "react";
import {Database, Network, BookOpen, Gauge, ShieldCheck, MessageSquareText, Settings2} from "lucide-react";

const sections=[
 ["Data Sources",Database,"Connect and test databases"],["Schema Explorer",Network,"Inspect tables, columns and relationships"],
 ["Semantic Model",BookOpen,"Define entities, attributes and synonyms"],["Metrics",Gauge,"Define reusable business metrics"],
 ["Business Rules",ShieldCheck,"Manage governed business definitions"],["Query Playground",MessageSquareText,"Inspect NL-to-SQL execution"],
] as const;
type Form={name:string;host:string;port:number;database:string;username:string;password:string;sslmode:"disable"|"prefer"|"require"};
type Column={name:string;data_type:string;is_nullable:boolean;is_primary_key:boolean};
type Table={name:string;schema_name?:string;columns:Column[];primary_keys:string[];foreign_keys:{constrained_column:string;referenced_table:string;referenced_column:string}[]};
type Schema={schema_name?:string;tables:Table[];dialect:string};
const API="http://localhost:8000";

export function App(){
 const [active,setActive]=useState("Data Sources");
 const [form,setForm]=useState<Form>({name:"AdventureWorks",host:"localhost",port:5432,database:"postgres",username:"postgres",password:"",sslmode:"disable"});
 const [message,setMessage]=useState(""); const [busy,setBusy]=useState(false); const [schemas,setSchemas]=useState<Schema[]>([]);
 const [semanticTables,setSemanticTables]=useState<any[]>([]); const [entities,setEntities]=useState<any[]>([]);
 const [entity,setEntity]=useState({name:"",description:"",table:"",key_column:"",display_column:"",synonyms:""});
 const update=(key:keyof Form,value:string|number)=>setForm({...form,[key]:value});
 async function call(path:string){setBusy(true);setMessage("");try{const r=await fetch(API+path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(form)});const data=await r.json();if(!r.ok)throw new Error(data.message||data.detail||"Request failed");return data}catch(e){setMessage(e instanceof Error?e.message:"Request failed");throw e}finally{setBusy(false)}}
 async function test(){try{const d=await call("/api/admin/data-sources/test");setMessage(d.message)}catch{}}
 async function discover(){try{const d=await call("/api/admin/data-sources/discover");setSchemas(d.schemas);setMessage(`Discovered ${d.schemas.reduce((n: number,s:Schema)=>n+s.tables.length,0)} tables across ${d.schemas.length} schemas`);setActive("Schema Explorer")}catch{}}
 async function loadSemantic(){setBusy(true);try{const r=await fetch(API+"/api/admin/semantic/"+encodeURIComponent(form.name)+"/catalog");const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to load semantic catalog");setSemanticTables(d.tables);setEntities(d.entities)}catch(e){setMessage(e instanceof Error?e.message:"Unable to load semantic catalog")}finally{setBusy(false)}}
 async function saveEntity(){const table=semanticTables.find(t=>`${t.schema_name}.${t.table_name}`===entity.table);if(!table)return;setBusy(true);try{const r=await fetch(API+"/api/admin/semantic/entities",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source_name:form.name,name:entity.name,description:entity.description||null,schema_name:table.schema_name,table_name:table.table_name,key_column:entity.key_column,display_column:entity.display_column||null,synonyms:entity.synonyms.split(",").map(x=>x.trim()).filter(Boolean),attributes:[]})});const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to save entity");setMessage(d.message);setEntity({name:"",description:"",table:"",key_column:"",display_column:"",synonyms:""});await loadSemantic()}catch(e){setMessage(e instanceof Error?e.message:"Unable to save entity")}finally{setBusy(false)}}
 return <div className="shell"><aside><div className="brand"><div className="mark">DP</div><div><strong>Data Pilot</strong><span>Admin Studio</span></div></div>
 <nav>{sections.map(([name,Icon])=><button className={active===name?"active":""} onClick={()=>{setActive(name);if(name==="Semantic Model")loadSemantic()}} key={name}><Icon size={18}/>{name}</button>)}</nav><div className="asideFoot"><Settings2 size={17}/>Local development</div></aside>
 <main><header><div><p className="eyebrow">OPEN-SOURCE CORE</p><h1>{active}</h1></div><div className="status"><i/>{schemas.length?"Schema discovered":"Local configuration"}</div></header>
 <section className="intro"><h2>{sections.find(x=>x[0]===active)?.[2]}</h2><p>Configure and inspect Data Pilot without editing source code. Connection credentials are used for this browser session and are not persisted by these endpoints.</p></section>
 {active==="Data Sources"&&<section className="grid"><article className="wide"><div className="cardTitle"><Database size={20}/><h3>PostgreSQL connection</h3><span>Development</span></div>
 <div className="formGrid"><label>Name<input value={form.name} onChange={e=>update("name",e.target.value)}/></label><label>Host<input value={form.host} onChange={e=>update("host",e.target.value)}/></label>
 <label>Port<input type="number" value={form.port} onChange={e=>update("port",Number(e.target.value))}/></label><label>Database<input value={form.database} onChange={e=>update("database",e.target.value)}/></label>
 <label>Username<input value={form.username} onChange={e=>update("username",e.target.value)}/></label><label>Password<input type="password" value={form.password} onChange={e=>update("password",e.target.value)}/></label></div>
 <div className="actions"><button onClick={test} disabled={busy||!form.password}>Test connection</button><button className="primary" onClick={discover} disabled={busy||!form.password}>Discover schema</button></div>{message&&<p className="notice">{message}</p>}</article></section>}
 {active==="Schema Explorer"&&<section>{schemas.length===0?<article className="wide"><div className="empty">Connect a data source and run schema discovery first.</div></article>:schemas.map(s=><article className="schema" key={s.schema_name}><h3>{s.schema_name} <span>{s.tables.length} tables/views</span></h3>{s.tables.map(t=><details key={t.name}><summary>{t.name}<small>{t.columns.length} columns · {t.primary_keys.length} PK · {t.foreign_keys.length} FK</small></summary><div className="columns">{t.columns.map(c=><div key={c.name}><code>{c.name}</code><span>{c.data_type}</span>{c.is_primary_key&&<b>PK</b>}</div>)}</div></details>)}</article>)}</section>}
 {active==="Semantic Model"&&<section className="grid"><article><h3>Add semantic entity</h3><div className="semanticForm">
 <label>Business name<input value={entity.name} onChange={e=>setEntity({...entity,name:e.target.value})} placeholder="Customer"/></label>
 <label>Description<textarea value={entity.description} onChange={e=>setEntity({...entity,description:e.target.value})}/></label>
 <label>Physical table<select value={entity.table} onChange={e=>setEntity({...entity,table:e.target.value,key_column:"",display_column:""})}><option value="">Select table…</option>{semanticTables.map(t=><option key={t.schema_name+"."+t.table_name} value={t.schema_name+"."+t.table_name}>{t.schema_name}.{t.table_name}</option>)}</select></label>
 {(()=>{const t=semanticTables.find(x=>x.schema_name+"."+x.table_name===entity.table);const cols=t?.columns||[];return <><label>Key column<select value={entity.key_column} onChange={e=>setEntity({...entity,key_column:e.target.value})}><option value="">Select key…</option>{cols.map((x:any)=><option key={x.name} value={x.name}>{x.name}{x.is_primary_key?" (PK)":""}</option>)}</select></label>
 <label>Display column<select value={entity.display_column} onChange={e=>setEntity({...entity,display_column:e.target.value})}><option value="">None</option>{cols.map((x:any)=><option key={x.name} value={x.name}>{x.name}</option>)}</select></label></>})()}
 <label>Synonyms<input value={entity.synonyms} onChange={e=>setEntity({...entity,synonyms:e.target.value})} placeholder="customer, client, buyer"/></label></div>
 <button className="primary" disabled={busy||!entity.name||!entity.table||!entity.key_column} onClick={saveEntity}>Save entity</button>{message&&<p className="notice">{message}</p>}</article>
 <article><h3>Configured entities</h3>{entities.length===0?<div className="empty">No semantic entities yet.</div>:entities.map(e=><div className="entityCard" key={e.id}><strong>{e.name}</strong><span>{e.schema_name}.{e.table_name}</span><p>{e.description||"No description"}</p><small>{e.synonyms.length?e.synonyms.join(", "):"No synonyms"}</small></div>)}</article></section>}
 {!["Data Sources","Schema Explorer","Semantic Model"].includes(active)&&<section className="grid"><article className="wide"><h3>{active} foundation</h3><p>This is the next configuration surface after data-source discovery.</p><div className="empty">No configuration has been created yet.</div></article></section>}
 </main></div>
}