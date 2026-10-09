import {useEffect,useState} from "react";
import {Database, Network, BookOpen, Gauge, ShieldCheck, MessageSquareText, Settings2, CalendarDays} from "lucide-react";

const sections=[
 ["Data Sources",Database,"Connect and test databases"],["AI Provider",Settings2,"Manage saved model and credential"],["Schema Explorer",Network,"Inspect tables, columns and relationships"],
 ["Semantic Model",BookOpen,"Define entities, attributes and synonyms"],["Metrics",Gauge,"Define reusable business metrics"],
 ["Business Rules",ShieldCheck,"Manage governed business definitions"],["Time Semantics",CalendarDays,"Govern date roles and relative calendar interpretation"],["Query Playground",MessageSquareText,"Inspect NL-to-SQL execution"],
] as const;
type Form={name:string;host:string;port:number;database:string;username:string;password:string;sslmode:"disable"|"prefer"|"require"};
type Column={name:string;data_type:string;is_nullable:boolean;is_primary_key:boolean};
type Table={name:string;schema_name?:string;columns:Column[];primary_keys:string[];foreign_keys:{constrained_column:string;referenced_table:string;referenced_column:string}[]};
type Schema={schema_name?:string;tables:Table[];dialect:string};
type SemanticAttribute={name:string;description:string;column_name:string;synonyms:string;operators:string[];value_mappings:string};
type SemanticEntityForm={id?:number;name:string;description:string;table:string;key_column:string;display_column:string;synonyms:string;attributes:SemanticAttribute[]};
const emptyEntity=():SemanticEntityForm=>({name:"",description:"",table:"",key_column:"",display_column:"",synonyms:"",attributes:[]});
const API="";

function displayValue(value:any){
 if(value===null||value===undefined)return "—";
 if(typeof value==="number")return new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(value);
 return String(value);
}
function ResultVisualization({response}:{response:any}){
 const result=response?.result; const plan=response?.presentation;
 if(!result?.columns?.length||!plan||plan.kind==="empty")return null;
 const columns:string[]=result.columns||[]; const rows:any[][]=result.rows||[];
 const comparisonCategoryIndices=columns.map((_:string,i:number)=>i).filter((i:number)=>rows.some((r:any[])=>r[i]!==null&&r[i]!==undefined&&typeof r[i]!=="number"&&isNaN(Number(r[i]))));
 const comparisonMeasureIndices=columns.map((_:string,i:number)=>i).filter((i:number)=>rows.length>0&&rows.every((r:any[])=>r[i]===null||r[i]===undefined||typeof r[i]==="number"||typeof r[i]==="string"&&r[i].trim()!==""&&Number.isFinite(Number(r[i]))));
 const groupedComparison=plan.kind==="comparison"&&plan.recommended_visual==="bar"&&comparisonCategoryIndices.length===2&&comparisonMeasureIndices.length===1&&rows.length>0;
 if(groupedComparison){
  const [categoryIndex,seriesIndex]=comparisonCategoryIndices,measureIndex=comparisonMeasureIndices[0];
  const categories=Array.from(new Set(rows.map((r:any[])=>String(r[categoryIndex]??"")))).sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  const series=Array.from(new Set(rows.map((r:any[])=>String(r[seriesIndex]??"")))).sort((a,b)=>a.localeCompare(b));
  if(categories.length<=40&&series.length>=2&&series.length<=8){
   const width=900,height=330,left=65,right=20,top=25,bottom=70,plotW=width-left-right,plotH=height-top-bottom;
   const max=Math.max(1,...rows.map((r:any[])=>Number(r[measureIndex])||0));
   const barGroup=plotW/categories.length,barWidth=Math.max(2,Math.min(36,barGroup*.75/series.length));
   const palette=["#2563eb","#f97316","#16a34a","#a855f7","#dc2626","#0891b2","#ca8a04","#64748b"];
   const lookup=new Map(rows.map((r:any[])=>[String(r[categoryIndex]??"")+"\\u0000"+String(r[seriesIndex]??""),Number(r[measureIndex])||0]));
   return <div className="presentationPanel"><div className="presentationHeading"><div><strong>Comparison by {columns[categoryIndex]}</strong><span>{columns[measureIndex]} by {columns[seriesIndex]}</span></div><em>Grouped · bar</em></div><div className="chartWrap"><svg className="resultChart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Grouped comparison of ${columns[measureIndex]} by ${columns[categoryIndex]} and ${columns[seriesIndex]}`}>
    {[0,.25,.5,.75,1].map((fraction:number)=><g key={fraction}><line x1={left} x2={width-right} y1={top+plotH*(1-fraction)} y2={top+plotH*(1-fraction)} className="chartGrid"/><text x={left-8} y={top+plotH*(1-fraction)+4} textAnchor="end" className="chartLabel">{displayValue(max*fraction)}</text></g>)}
    {categories.map((category:string,ci:number)=><g key={category}>{series.map((name:string,si:number)=>{const value=lookup.get(category+"\\u0000"+name)||0;const h=Math.max(0,value/max*plotH);return <rect key={name} x={left+ci*barGroup+(barGroup-series.length*barWidth)/2+si*barWidth} y={top+plotH-h} width={Math.max(1,barWidth-2)} height={h} rx="2" fill={palette[si%palette.length]}><title>{category} · {name}: {displayValue(value)}</title></rect>})}{ci%Math.max(1,Math.ceil(categories.length/15))===0&&<text x={left+ci*barGroup+barGroup/2} y={height-38} textAnchor="middle" className="chartLabel">{category.slice(0,15)}</text>}</g>)}
   </svg></div><div className="chartLegend">{series.map((name:string,i:number)=><span key={name}><span style={{color:palette[i%palette.length]}}>●</span> {name}</span>)}</div></div>;
  }
 }
 // Generic ranked categorical bar chart; preserve raw data ordering.
 if(plan.recommended_visual==="bar"&&plan.kind!=="trend"&&comparisonCategoryIndices.length===1&&comparisonMeasureIndices.length===1&&rows.length>0&&rows.length<=100){
  const ci=comparisonCategoryIndices[0],mi=comparisonMeasureIndices[0];
  if(ci!==mi&&rows.every((r:any[])=>r[mi]!=null&&Number.isFinite(Number(r[mi]))&&Number(r[mi])>=0)){
   const ranked=[...rows].sort((a:any[],b:any[])=>Number(b[mi])-Number(a[mi])||String(a[ci]??"").localeCompare(String(b[ci]??"")));
   const width=900,left=230,right=90,top=20,rowHeight=30,bottom=34;
   const height=top+ranked.length*rowHeight+bottom,plotW=width-left-right,max=Math.max(1,...ranked.map((r:any[])=>Number(r[mi])));
   return <div className="presentationPanel"><div className="presentationHeading"><div><strong>Comparison by {columns[ci]}</strong><span>{columns[mi]} · highest to lowest</span></div><em>Auto · ranked bars</em></div><div className="chartWrap"><svg className="resultChart rankedChart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${columns[mi]} ranked by ${columns[ci]}`}>
    {[0,.25,.5,.75,1].map((fraction:number)=><g key={fraction}><line x1={left+plotW*fraction} x2={left+plotW*fraction} y1={top-6} y2={height-bottom} className="chartGrid"/><text x={left+plotW*fraction} y={height-9} textAnchor="middle" className="chartLabel">{displayValue(max*fraction)}</text></g>)}
    {ranked.map((r:any[],i:number)=>{const label=String(r[ci]??"—"),value=Number(r[mi]),y=top+i*rowHeight;return <g key={i}><text x={left-12} y={y+17} textAnchor="end" className="chartLabel"><title>{label}</title>{label.length>32?label.slice(0,29)+"…":label}</text><rect x={left} y={y+3} width={Math.max(0,value/max*plotW)} height={20} rx="3" fill="#2563eb"><title>{label}: {displayValue(value)}</title></rect><text x={left+Math.max(0,value/max*plotW)+7} y={y+17} className="chartLabel">{displayValue(value)}</text></g>})}
   </svg></div></div>;
  }
 }
 const xIndex=plan.x_column?columns.indexOf(plan.x_column):-1;
 const yColumns:string[]=plan.y_columns||[]; const yIndices=yColumns.map((y:string)=>columns.indexOf(y)).filter((i:number)=>i>=0);
 if(plan.recommended_visual==="kpi"&&yIndices.length){
  return <div className="presentationPanel"><div className="presentationHeading"><div><strong>{yColumns[0]}</strong><span>KPI · {plan.reason}</span></div><em>Auto</em></div><div className="kpiValue">{displayValue(rows[0]?.[yIndices[0]])}</div></div>
 }
 if((plan.recommended_visual==="bar"||plan.recommended_visual==="line")&&xIndex>=0&&yIndices.length&&rows.length){
  const width=900,height=300,left=64,right=20,top=24,bottom=58,plotW=width-left-right,plotH=height-top-bottom;
  const values=rows.flatMap((r:any[])=>yIndices.map((i:number)=>Number(r[i])).filter(Number.isFinite));
  const minRaw=Math.min(...values),maxRaw=Math.max(...values); const min=Math.min(0,minRaw); const max=maxRaw===min?min+1:maxRaw;
  const y=(v:number)=>top+plotH-((v-min)/(max-min))*plotH;
  const x=(ri:number)=>left+(rows.length===1?plotW/2:(ri/(rows.length-1))*plotW);
  const barGroup=plotW/Math.max(rows.length,1),barWidth=Math.max(4,Math.min(48,(barGroup*.72)/Math.max(yIndices.length,1)));
  const trendInsights:any[]=response?.result_summary?.insights||[]; const turningPoints=trendInsights.filter((item:any)=>item.type==="turning_point"); const momentum=trendInsights.find((item:any)=>item.type==="strongest_momentum_change");
  return <div className="presentationPanel"><div className="presentationHeading"><div><strong>{plan.kind==="trend"?"Trend":plan.kind==="ranking"?"Ranking":"Comparison"}</strong><span>{plan.reason}</span></div><em>Auto · {plan.recommended_visual}</em></div>
   <div className="chartWrap"><svg className="resultChart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={plan.reason||"Result chart"}>
    <line x1={left} y1={top+plotH} x2={width-right} y2={top+plotH} className="chartAxis"/>
    <line x1={left} y1={top} x2={left} y2={top+plotH} className="chartAxis"/>
    {[0,.25,.5,.75,1].map((t:number)=>{const val=min+(max-min)*t,py=y(val);return <g key={t}><line x1={left} y1={py} x2={width-right} y2={py} className="chartGrid"/><text x={left-8} y={py+4} textAnchor="end" className="chartLabel">{displayValue(val)}</text></g>})}
    {plan.recommended_visual==="line"?yIndices.map((yi:number,si:number)=>{const valid=rows.map((r:any[],ri:number)=>({ri,value:r[yi]})).filter((p:any)=>p.value!==null&&p.value!==undefined&&Number.isFinite(Number(p.value)));const segments:any[][]=[];let segment:any[]=[];rows.forEach((r:any[],ri:number)=>{const value=r[yi];if(value===null||value===undefined||!Number.isFinite(Number(value))){if(segment.length){segments.push(segment);segment=[]}}else segment.push({ri,value:Number(value)});});if(segment.length)segments.push(segment);return <g key={yi} className={"chartSeries series"+(si%4)}>{segments.filter(s=>s.length>1).map((s:any[],idx:number)=><polyline key={"line-"+idx} points={s.map(p=>`${x(p.ri)},${y(p.value)}`).join(" ")} className="chartLine"/>)}{valid.map((p:any)=><circle key={p.ri} cx={x(p.ri)} cy={y(Number(p.value))} r="4" className="chartPoint"/>)}</g>}):rows.flatMap((r:any[],ri:number)=>yIndices.map((yi:number,si:number)=>{if(r[yi]===null||r[yi]===undefined||!Number.isFinite(Number(r[yi])))return null;const v=Number(r[yi]),bx=left+ri*barGroup+(barGroup-yIndices.length*barWidth)/2+si*barWidth,by=y(Math.max(v,0)),base=y(Math.min(v,0));return <rect key={ri+"-"+si} x={bx} y={Math.min(by,base)} width={barWidth-2} height={Math.max(1,Math.abs(base-by))} rx="3" className={"chartBar series"+(si%4)}/> }))}
    {rows.map((r:any[],ri:number)=>{const every=Math.max(1,Math.ceil(rows.length/10));return ri%every===0?<text key={ri} x={plan.recommended_visual==="bar"?left+ri*barGroup+barGroup/2:x(ri)} y={height-30} textAnchor="middle" className="chartLabel">{String(r[xIndex]??"").slice(0,18)}</text>:null})}
   </svg></div>{plan.kind==="trend"&&(turningPoints.length>0||momentum)&&<div className="chartLegend">{turningPoints.slice(0,3).map((item:any,i:number)=><span key={"turn-"+i}>↳ {item.turning_type} · {String(item.label)}</span>)}{momentum&&momentum.momentum!=="steady"&&<span>↳ momentum · {momentum.momentum} · {String(momentum.from_label)} → {String(momentum.to_label)}</span>}</div>}{yColumns.length>1&&<div className="chartLegend">{yColumns.map((name:string,i:number)=><span key={name} className={"seriesText series"+(i%4)}>● {name}</span>)}</div>}</div>
 }
 return null;
}

export function App(){
 const [active,setActive]=useState("Data Sources");
 const [aiConfig,setAiConfig]=useState({provider:"gemini",model:"gemini-2.5-flash",endpoint:"",configured:false,credential_configured:false});
 const [aiKey,setAiKey]=useState("");
 const [aiMessage,setAiMessage]=useState("");
 const [aiBusy,setAiBusy]=useState(false);
 const [aiValidated,setAiValidated]=useState<boolean|null>(null);
 async function loadAiConfig(){
  try{
   const response=await fetch("/api/setup/ai-provider");
   if(!response.ok)throw new Error("Unable to load AI provider settings");
   const data=await response.json();
   setAiConfig({...data,endpoint:data.endpoint||""});
   const readinessResponse=await fetch("/api/setup/readiness");
   if(readinessResponse.ok){const readiness=await readinessResponse.json();setAiValidated(readiness.ai_provider==="ready");}
   else setAiValidated(null);
  }catch(error){setAiValidated(null);setAiMessage(error instanceof Error?error.message:"Unable to load AI settings")}
 }
 async function saveAiConfig(){
  setAiBusy(true);setAiMessage("");
  try{
   const response=await fetch("/api/setup/ai-provider",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider:aiConfig.provider,model:aiConfig.model,endpoint:aiConfig.endpoint||null,api_key:aiKey||null})});
   const data=await response.json();
   if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"Unable to save AI provider");
   setAiKey("");await loadAiConfig();setAiMessage("AI provider configuration saved. Check validation status below.");
  }catch(error){setAiMessage(error instanceof Error?error.message:"Unable to save AI provider")}
  finally{setAiBusy(false)}
 }

 const [form,setForm]=useState<Form>({name:"AdventureWorks",host:"localhost",port:5432,database:"postgres",username:"postgres",password:"",sslmode:"disable"});
 const [message,setMessage]=useState(""); const [busy,setBusy]=useState(false); const [schemas,setSchemas]=useState<Schema[]>([]);
 const [semanticTables,setSemanticTables]=useState<any[]>([]); const [entities,setEntities]=useState<any[]>([]); const [relationships,setRelationships]=useState<any[]>([]);
 const [datasets,setDatasets]=useState<any[]>([]); const [datasetKey,setDatasetKey]=useState("");
 const [dataset,setDataset]=useState({description:"",business_meaning:"",grain:"",identity_semantics:"",aliases:"",use_cases:"",query_constraints:""});
 const [relationship,setRelationship]=useState({name:"",from_entity_id:"",from_column:"",to_entity_id:"",to_column:"",cardinality:"many-to-one",description:""});
 const [entity,setEntity]=useState<SemanticEntityForm>(emptyEntity());
 const [bootstrapTable,setBootstrapTable]=useState("");
 const [bootstrapPreview,setBootstrapPreview]=useState<any>(null);
 const [bootstrapSelected,setBootstrapSelected]=useState<string[]>([]);
 const [bootstrapFilter,setBootstrapFilter]=useState<"new"|"all"|"existing">("new");
 const [bootstrapSearch,setBootstrapSearch]=useState("");
 const [bootstrapConfirmed,setBootstrapConfirmed]=useState(false);
 const [bootstrapBusy,setBootstrapBusy]=useState(false);
 const [bootstrapMessage,setBootstrapMessage]=useState("");
 async function previewBootstrap(){
  if(!bootstrapTable)return;
  const [schema_name,table_name]=bootstrapTable.split(".");
  setBootstrapBusy(true);setBootstrapMessage("");setBootstrapPreview(null);setBootstrapSelected([]);setBootstrapConfirmed(false);
  try{
   const r=await fetch(API+"/api/admin/semantic/bootstrap/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source_name:form.name,schema_name,table_name})});
   const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:"Unable to preview semantic bootstrap");
   setBootstrapPreview(d);setBootstrapConfirmed(false);
   const existing=entities.find((e:any)=>e.schema_name===schema_name&&e.table_name===table_name);
   const known=new Set((existing?.attributes||[]).map((a:any)=>a.column_name));
   setBootstrapSelected([]);
  }catch(e){setBootstrapMessage(e instanceof Error?e.message:"Preview failed")}finally{setBootstrapBusy(false)}
 }
 function stageBootstrap(){
  if(!bootstrapPreview||!bootstrapConfirmed||!bootstrapSelected.length)return;
  const d=bootstrapPreview;const table=d.schema_name+"."+d.table_name;
  const existing=entities.find((e:any)=>e.schema_name===d.schema_name&&e.table_name===d.table_name);
  const mapped=existing?(existing.attributes||[]).map((a:any)=>({name:a.name,description:a.description||"",column_name:a.column_name,synonyms:(a.synonyms||[]).join(", "),operators:a.operators||["="],value_mappings:(a.value_mappings||[]).map((v:any)=>v.canonical_value+" | "+(v.synonyms||[]).join(", ")).join("\n")})):[];
  const known=new Set(mapped.map((a:SemanticAttribute)=>a.column_name));
  const additions=(d.entity?.attributes||[]).filter((a:any)=>bootstrapSelected.includes(a.column_name)&&!known.has(a.column_name)).map((a:any)=>({name:a.name,description:a.description||"",column_name:a.column_name,synonyms:"",operators:a.operators||["="],value_mappings:""}));
  if(existing){editEntity(existing);setEntity(current=>({...current,attributes:[...mapped,...additions]}));}
  else{setEntity({name:d.entity?.name||"",description:d.entity?.description||"",table,key_column:d.entity?.key_column||"",display_column:d.entity?.display_column||"",synonyms:"",attributes:additions});setEditingAttributeIndex(null);}
  if(additions.length===1){setAttribute({...additions[0]});setEditingAttributeIndex(mapped.length);setBootstrapMessage("Attribute staged and opened for editing. Update the attribute, then save the entity to publish.");}
  else{setAttribute({name:"",description:"",column_name:"",synonyms:"",operators:["="],value_mappings:""});setEditingAttributeIndex(null);setBootstrapMessage("Suggestions staged in the entity editor; nothing has been saved. Review and click Save changes when ready.");}
  window.requestAnimationFrame(()=>document.getElementById("semantic-attribute-form")?.scrollIntoView({behavior:"smooth",block:"center"}));
 }

 const [attribute,setAttribute]=useState<SemanticAttribute>({name:"",description:"",column_name:"",synonyms:"",operators:["="],value_mappings:""}); const [editingAttributeIndex,setEditingAttributeIndex]=useState<number|null>(null);
 const [metrics,setMetrics]=useState<any[]>([]); const [metricEntities,setMetricEntities]=useState<any[]>([]);
 const [metric,setMetric]=useState({id:null as number|null,name:"",description:"",entity_id:"",metric_type:"simple",attribute_name:"",calculation_expression:"",aggregation:"sum",format:"number",synonyms:""});
 const [rules,setRules]=useState<any[]>([]); const [ruleEntities,setRuleEntities]=useState<any[]>([]); const [ruleMetrics,setRuleMetrics]=useState<any[]>([]);
 const [rule,setRule]=useState({id:null as number|null,name:"",description:"",rule_type:"definition",target_type:"entity",entity_id:"",metric_id:"",priority:100,enabled:true,keywords:""});
 const [timeDimensions,setTimeDimensions]=useState<any[]>([]); const [timeEntities,setTimeEntities]=useState<any[]>([]);
 const [timeDimension,setTimeDimension]=useState({id:null as number|null,name:"",entity_id:"",column_name:"",role:"event_time",grain:"day",timezone:"UTC",is_default:false,synonyms:""});
 const [queryQuestion,setQueryQuestion]=useState("Show revenue by product"); const [queryResponse,setQueryResponse]=useState<any>(null);
 const [queryHistory,setQueryHistory]=useState<any[]>([]); const [selectedHistory,setSelectedHistory]=useState<any>(null);
 const [playgroundTab,setPlaygroundTab]=useState<"query"|"history">("query");
 const [followUpTo,setFollowUpTo]=useState<{id:number;question:string}|null>(null);
 const [savedSourceId,setSavedSourceId]=useState<number|null>(null);
 const [categoryProposal,setCategoryProposal]=useState<{key:string;values:string[];complete:boolean;error:string}|null>(null);
 const [categoryBusy,setCategoryBusy]=useState(false);
 const [categoryReviewed,setCategoryReviewed]=useState<string[]>([]);
 const [categoryAliases,setCategoryAliases]=useState<Record<string,string>>({});
 const [categoryReviewMessage,setCategoryReviewMessage]=useState("");
 async function discoverCategory(schemaName:string,tableName:string,columnName:string){
  if(savedSourceId===null)return;
  const key=schemaName+"."+tableName+"."+columnName;
  setCategoryBusy(true);setCategoryProposal(null);setCategoryReviewed([]);setCategoryAliases({});setCategoryReviewMessage("");
  try{
   const response=await fetch("/api/setup/data-source/"+savedSourceId+"/categorical-proposals",{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({schema_name:schemaName,table_name:tableName,column_name:columnName})
   });
   const result=await response.json();
   if(!response.ok)throw new Error(result.detail||"Discovery failed");
   setCategoryProposal({key,values:result.values||[],complete:result.complete===true,error:""});
  }catch(error){
   setCategoryProposal({key,values:[],complete:false,error:error instanceof Error?error.message:"Discovery failed"});
  }finally{setCategoryBusy(false)}
 }

 async function publishCategoryMappings(){
  if(!categoryProposal||savedSourceId===null||!categoryReviewed.length)return;
  if(!categoryProposal.complete){setCategoryReviewMessage("Discovery is incomplete; cannot publish.");return}
  const parts=categoryProposal.key.split(".");
  if(parts.length!==3){setCategoryReviewMessage("Invalid discovered column.");return}
  setCategoryBusy(true);setCategoryReviewMessage("");
  try{
   const response=await fetch("/api/setup/data-source/"+savedSourceId+"/categorical-mappings/publish",{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({schema_name:parts[0],table_name:parts[1],column_name:parts[2],
     create_missing_attribute:window.confirm("If this column has no semantic attribute, create one on its existing semantic entity? Cancel publishes only if the attribute already exists."),
     mappings:categoryProposal.values.filter(v=>categoryReviewed.includes(v)).map(v=>({
      canonical_value:v,synonyms:(categoryAliases[v]||"").split(",").map(a=>a.trim()).filter(Boolean)
     }))})
   });
   const result=await response.json();
   if(!response.ok)throw new Error(typeof result.detail==="string"?result.detail:"Publication failed");
   setCategoryReviewMessage(result.count+" mapping(s) published. Existing mappings preserved.");
   await loadSemantic();
  }catch(error){setCategoryReviewMessage(error instanceof Error?error.message:"Publication failed")}
  finally{setCategoryBusy(false)}
 }
 const [savedSourceName,setSavedSourceName]=useState("");
 const [connectionTestName,setConnectionTestName]=useState("AdventureWorks");
 const [savedSourceDetails,setSavedSourceDetails]=useState<{host:string;port:number;database:string;username:string;sslmode:string}|null>(null);
 const [savedSourceTestMessage,setSavedSourceTestMessage]=useState("");
 const [savedSourceTesting,setSavedSourceTesting]=useState(false);
 const [newLoginUsername,setNewLoginUsername]=useState("");
 const [newLoginPassword,setNewLoginPassword]=useState("");
 const [loginBusy,setLoginBusy]=useState(false);
 const [loginStatus,setLoginStatus]=useState("");
 async function updateSavedLogin(){
  if(savedSourceId===null||!newLoginUsername.trim()||!newLoginPassword)return;
  setLoginBusy(true);setLoginStatus("");
  try{
   const response=await fetch(API+"/api/setup/data-source/"+savedSourceId+"/login",{
    method:"PUT",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({username:newLoginUsername.trim(),password:newLoginPassword})
   });
   if(!response.ok)throw new Error("Login validation or update failed. Test the saved connection before retrying.");
   setNewLoginPassword("");setLoginStatus("Login updated successfully.");
   setSavedSourceDetails(previous=>previous?{...previous,username:newLoginUsername.trim()}:previous);
  }catch(error){setLoginStatus(error instanceof Error?error.message:"Login update failed.");}
  finally{setLoginBusy(false);}
 }
 const [newCredential,setNewCredential]=useState("");
 const [credentialStatus,setCredentialStatus]=useState("");
 const [credentialBusy,setCredentialBusy]=useState(false);
 async function updateCredential(){
  if(savedSourceId===null)return;
  setCredentialBusy(true);setCredentialStatus("");
  try{
   const response=await fetch(API+"/api/setup/data-source/"+savedSourceId+"/credential",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:newCredential})});
   if(!response.ok)throw new Error("Validation failed; the previous credential was not replaced.");
   setNewCredential("");setCredentialStatus("Credential updated successfully.");
  }catch(error){setCredentialStatus(error instanceof Error?error.message:"Update failed");}
  finally{setCredentialBusy(false);}
 }

 async function testSavedSource(){
  if(savedSourceId===null)return;
  setSavedSourceTesting(true);setSavedSourceTestMessage("");
  try{
   const response=await fetch(API+"/api/setup/data-source/"+savedSourceId+"/test",{method:"POST"});
   if(!response.ok)throw new Error("Saved connection test failed. Check connectivity and stored credentials.");
   setSavedSourceTestMessage("Saved datasource connection successful.");
  }catch(error){setSavedSourceTestMessage(error instanceof Error?error.message:"Saved connection test failed.")}
  finally{setSavedSourceTesting(false)}
 }

 const [sourceRestoreError,setSourceRestoreError]=useState("");
 useEffect(()=>{
  let cancelled=false;
  async function restore(){
   try{
    const response=await fetch(API+"/api/setup/data-source/active");
    if(!response.ok)throw new Error("No active saved datasource is available.");
    const source=await response.json();
    const catalogResponse=await fetch(API+"/api/setup/data-source/"+source.id+"/datasets");
    if(!catalogResponse.ok)throw new Error("Unable to restore the discovered schema catalog.");
    const catalog=await catalogResponse.json();
    if(cancelled)return;
    setSavedSourceId(source.id);
    setSavedSourceName(source.name);
    const detailsResponse=await fetch(API+"/api/setup/data-source/"+source.id+"/details");
    if(detailsResponse.ok){
     const details=await detailsResponse.json();
     if(!cancelled)setSavedSourceDetails({host:details.host,port:details.port,database:details.database,username:details.username,sslmode:details.sslmode});
    }
    setForm(previous=>({...previous,name:source.name,password:""}));
    const bySchema=new Map<string,any[]>();
    for(const table of catalog.datasets||[]){
     const list=bySchema.get(table.schema_name)||[];
     list.push({name:table.table_name,columns:(table.columns||[]).map((column:any)=>({
      name:column.name,data_type:column.data_type,is_primary_key:Boolean(column.is_primary_key)
     })),primary_keys:(table.columns||[]).filter((column:any)=>column.is_primary_key).map((column:any)=>column.name),
     foreign_keys:table.foreign_keys||[]});
     bySchema.set(table.schema_name,list);
    }
    setSchemas(Array.from(bySchema,([schema_name,tables])=>({schema_name,tables})) as Schema[]);
    setSourceRestoreError("");
   }catch(e){if(!cancelled)setSourceRestoreError(e instanceof Error?e.message:"Unable to restore saved datasource")}
  }
  restore();
  return ()=>{cancelled=true};
 },[]);
 const update=(key:keyof Form,value:string|number)=>setForm({...form,[key]:value});
 async function runQuery(dryRun=false,clarificationSelections:Record<string,string>={}){setPlaygroundTab("query");setBusy(true);setMessage("");setSelectedHistory(null);setQueryResponse(null);try{const r=await fetch(API+"/api/query",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:queryQuestion,source_name:form.name,parameters:{},dry_run:dryRun,clarification_selections:clarificationSelections,follow_up_to_history_id:followUpTo?.id||null})});const d=await r.json();if(!r.ok)throw new Error(d.message||d.detail||"Query failed");setQueryResponse(d);await loadQueryHistory()}catch(e){setMessage(e instanceof Error?e.message:"Query failed")}finally{setBusy(false)}}
 function continueFromResult(){
  const id=Number(queryResponse?.history_id||selectedHistory?.id||0);
  if(!id)return;
  setFollowUpTo({id,question:queryResponse?.question||selectedHistory?.question||queryQuestion});
  setQueryQuestion("");
  setQueryResponse(null);
  setSelectedHistory(null);
  setMessage("");
  setPlaygroundTab("query");
 }
 function startNewQuery(){setFollowUpTo(null);setQueryQuestion("");setQueryResponse(null);setSelectedHistory(null);setMessage("");setPlaygroundTab("query")}
 async function loadQueryHistory(){try{const r=await fetch(API+"/api/query/history?source_name="+encodeURIComponent(form.name)+"&limit=20");const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to load query history");setQueryHistory(d)}catch(e){setMessage(e instanceof Error?e.message:"Unable to load query history")}}
 async function openQueryHistory(id:number){setBusy(true);setMessage("");try{const r=await fetch(API+"/api/query/history/"+id);const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to load historical query");setQueryQuestion(d.question);setSelectedHistory(d);setQueryResponse(d.response);setPlaygroundTab("query")}catch(e){setMessage(e instanceof Error?e.message:"Unable to load historical query")}finally{setBusy(false)}}
 async function call(path:string){setBusy(true);setMessage("");try{const r=await fetch(API+path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(form)});const data=await r.json();if(!r.ok)throw new Error(data.message||data.detail||"Request failed");return data}catch(e){setMessage(e instanceof Error?e.message:"Request failed");throw e}finally{setBusy(false)}}
 async function test(){try{const d=await call("/api/admin/data-sources/test");setMessage(d.message)}catch{}}
 async function discover(){try{const d=await call("/api/admin/data-sources/discover");setSchemas(d.schemas);setMessage(`Discovered ${d.schemas.reduce((n: number,s:Schema)=>n+s.tables.length,0)} tables across ${d.schemas.length} schemas`);setActive("Schema Explorer")}catch{}}
 async function loadTimeDimensions(){setBusy(true);setMessage("");try{const r=await fetch(API+"/api/admin/semantic/"+encodeURIComponent(form.name)+"/time-dimensions");const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to load time semantics");setTimeEntities(d.entities||[]);setTimeDimensions(d.time_dimensions||[])}catch(e){setMessage(e instanceof Error?e.message:"Unable to load time semantics")}finally{setBusy(false)}}
 async function saveTimeDimension(){setBusy(true);setMessage("");try{const r=await fetch(API+"/api/admin/semantic/time-dimensions",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source_name:form.name,name:timeDimension.name,entity_id:Number(timeDimension.entity_id),column_name:timeDimension.column_name,role:timeDimension.role,grain:timeDimension.grain,timezone:timeDimension.timezone,is_default:timeDimension.is_default,synonyms:timeDimension.synonyms.split(",").map(x=>x.trim()).filter(Boolean)})});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:"Unable to save time dimension");setMessage(d.message);setTimeDimension({id:null,name:"",entity_id:"",column_name:"",role:"event_time",grain:"day",timezone:"UTC",is_default:false,synonyms:""});await loadTimeDimensions()}catch(e){setMessage(e instanceof Error?e.message:"Unable to save time dimension")}finally{setBusy(false)}}
 function editTimeDimension(t:any){setTimeDimension({id:t.id,name:t.name||"",entity_id:String(t.entity_id||""),column_name:t.column_name||"",role:t.role||"event_time",grain:t.grain||"day",timezone:t.timezone||"UTC",is_default:t.is_default===true,synonyms:(t.synonyms||[]).join(", ")});setMessage("")}
 function cancelTimeEdit(){setTimeDimension({id:null,name:"",entity_id:"",column_name:"",role:"event_time",grain:"day",timezone:"UTC",is_default:false,synonyms:""});setMessage("")}
 async function loadRules(){setBusy(true);setMessage("");try{const r=await fetch(API+"/api/admin/semantic/"+encodeURIComponent(form.name)+"/business-rules");const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to load business rules");setRuleEntities(d.entities||[]);setRuleMetrics(d.metrics||[]);setRules(d.rules||[])}catch(e){setMessage(e instanceof Error?e.message:"Unable to load business rules")}finally{setBusy(false)}}
 async function saveRule(){setBusy(true);try{const r=await fetch(API+"/api/admin/semantic/business-rules",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source_name:form.name,name:rule.name,description:rule.description,rule_type:rule.rule_type,entity_id:rule.target_type==="entity"?Number(rule.entity_id):null,metric_id:rule.target_type==="metric"?Number(rule.metric_id):null,priority:rule.priority,enabled:rule.enabled,keywords:rule.keywords.split(",").map(x=>x.trim()).filter(Boolean)})});const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to save business rule");setMessage(d.message);setRule({id:null,name:"",description:"",rule_type:"definition",target_type:"entity",entity_id:"",metric_id:"",priority:100,enabled:true,keywords:""});await loadRules()}catch(e){setMessage(e instanceof Error?e.message:"Unable to save business rule")}finally{setBusy(false)}}
 async function loadMetrics(){setBusy(true);setMessage("");try{const r=await fetch(API+"/api/admin/semantic/"+encodeURIComponent(form.name)+"/metrics");const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to load metrics");setMetricEntities(d.entities||[]);setMetrics(d.metrics||[])}catch(e){setMessage(e instanceof Error?e.message:"Unable to load metrics")}finally{setBusy(false)}}
 async function saveMetric(){setBusy(true);try{const r=await fetch(API+"/api/admin/semantic/metrics",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source_name:form.name,name:metric.name,description:metric.description||null,entity_id:Number(metric.entity_id),attribute_name:metric.metric_type==="simple"?metric.attribute_name:null,calculation_expression:metric.metric_type==="derived"?metric.calculation_expression:null,aggregation:metric.aggregation,format:metric.format,synonyms:metric.synonyms.split(",").map(x=>x.trim()).filter(Boolean)})});const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==="string"?d.detail:(d.message||"Unable to save metric"));setMessage(d.message);setMetric({id:null,name:"",description:"",entity_id:"",metric_type:"simple",attribute_name:"",calculation_expression:"",aggregation:"sum",format:"number",synonyms:""});await loadMetrics()}catch(e){setMessage(e instanceof Error?e.message:"Unable to save metric")}finally{setBusy(false)}}
 function editMetric(m:any){setMetric({id:m.id,name:m.name||"",description:m.description||"",entity_id:String(m.entity_id||""),metric_type:m.metric_type|| (m.calculation_expression?"derived":"simple"),attribute_name:m.attribute_name||"",calculation_expression:m.calculation_expression||"",aggregation:m.aggregation||"sum",format:m.format||"number",synonyms:(m.synonyms||[]).join(", ")});setMessage("")}
 function cancelMetricEdit(){setMetric({id:null,name:"",description:"",entity_id:"",metric_type:"simple",attribute_name:"",calculation_expression:"",aggregation:"sum",format:"number",synonyms:""});setMessage("")}
 function editRule(r:any){setRule({id:r.id,name:r.name||"",description:r.description||"",rule_type:r.rule_type||"definition",target_type:r.metric_id?"metric":"entity",entity_id:r.entity_id?String(r.entity_id):"",metric_id:r.metric_id?String(r.metric_id):"",priority:r.priority||100,enabled:r.enabled!==false,keywords:(r.keywords||[]).join(", ")});setMessage("")}
 function cancelRuleEdit(){setRule({id:null,name:"",description:"",rule_type:"definition",target_type:"entity",entity_id:"",metric_id:"",priority:100,enabled:true,keywords:""});setMessage("")}
 async function loadSemantic(){setBusy(true);try{const r=await fetch(API+"/api/admin/semantic/"+encodeURIComponent(form.name)+"/catalog");const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to load semantic catalog");setSemanticTables(d.tables);setEntities(d.entities);setRelationships(d.relationships||[])}catch(e){setMessage(e instanceof Error?e.message:"Unable to load semantic catalog")}finally{setBusy(false)}}
 async function loadDatasets(){try{const r=await fetch(API+"/api/admin/semantic/"+encodeURIComponent(form.name)+"/datasets");const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to load dataset semantics");setSemanticTables(d.tables||[]);setDatasets(d.datasets||[])}catch(e){setMessage(e instanceof Error?e.message:"Unable to load dataset semantics")}}
 function selectDataset(key:string){setDatasetKey(key);const configured=datasets.find((d:any)=>d.schema_name+"."+d.table_name===key);setDataset(configured?{description:configured.description||"",business_meaning:configured.business_meaning||"",grain:configured.grain||"",identity_semantics:configured.identity_semantics||"",aliases:(configured.aliases||[]).join(", "),use_cases:(configured.use_cases||[]).join("\n"),query_constraints:(configured.query_constraints||[]).join("\n")}:{description:"",business_meaning:"",grain:"",identity_semantics:"",aliases:"",use_cases:"",query_constraints:""});}
 async function saveDataset(){const physical=semanticTables.find((t:any)=>t.schema_name+"."+t.table_name===datasetKey);if(!physical)return;setBusy(true);setMessage("");try{const lines=(v:string)=>v.split("\n").map(x=>x.trim()).filter(Boolean);const r=await fetch(API+"/api/admin/semantic/datasets",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source_name:form.name,schema_name:physical.schema_name,table_name:physical.table_name,description:dataset.description||null,business_meaning:dataset.business_meaning||null,grain:dataset.grain||null,identity_semantics:dataset.identity_semantics||null,aliases:dataset.aliases.split(",").map(x=>x.trim()).filter(Boolean),use_cases:lines(dataset.use_cases),query_constraints:lines(dataset.query_constraints)})});const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to save dataset semantics");setMessage(d.message);await loadDatasets()}catch(e){setMessage(e instanceof Error?e.message:"Unable to save dataset semantics")}finally{setBusy(false)}}
 function editEntity(e:any){setEntity({id:e.id,name:e.name,description:e.description||"",table:`${e.schema_name}.${e.table_name}`,key_column:e.key_column,display_column:e.display_column||"",synonyms:(e.synonyms||[]).join(", "),attributes:(e.attributes||[]).map((a:any)=>({name:a.name,description:a.description||"",column_name:a.column_name,synonyms:(a.synonyms||[]).join(", "),operators:a.operators||["="],value_mappings:(a.value_mappings||[]).map((v:any)=>v.canonical_value+" | "+(v.synonyms||[]).join(", ")).join("\n")}))});setAttribute({name:"",description:"",column_name:"",synonyms:"",operators:["="],value_mappings:""});setEditingAttributeIndex(null);}
 function addAttribute(){if(!attribute.name||!attribute.column_name)return;setEntity({...entity,attributes:editingAttributeIndex===null?[...entity.attributes,attribute]:entity.attributes.map((a,i)=>i===editingAttributeIndex?attribute:a)});setAttribute({name:"",description:"",column_name:"",synonyms:"",operators:["="],value_mappings:""});setEditingAttributeIndex(null);}
 function editAttribute(index:number){setAttribute({...entity.attributes[index]});setEditingAttributeIndex(index);}
 function cancelAttributeEdit(){setAttribute({name:"",description:"",column_name:"",synonyms:"",operators:["="],value_mappings:""});setEditingAttributeIndex(null);}
 function removeAttribute(index:number){setEntity({...entity,attributes:entity.attributes.filter((_,i)=>i!==index)});if(editingAttributeIndex===index)cancelAttributeEdit();else if(editingAttributeIndex!==null&&editingAttributeIndex>index)setEditingAttributeIndex(editingAttributeIndex-1);}
 function toggleOperator(op:string){setAttribute({...attribute,operators:attribute.operators.includes(op)?attribute.operators.filter(x=>x!==op):[...attribute.operators,op]});}
 async function saveRelationship(){setBusy(true);try{const r=await fetch(API+"/api/admin/semantic/relationships",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...relationship,source_name:form.name,from_entity_id:Number(relationship.from_entity_id),to_entity_id:Number(relationship.to_entity_id),description:relationship.description||null})});const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to save relationship");setMessage(d.message);setRelationship({name:"",from_entity_id:"",from_column:"",to_entity_id:"",to_column:"",cardinality:"many-to-one",description:""});await loadSemantic()}catch(e){setMessage(e instanceof Error?e.message:"Unable to save relationship")}finally{setBusy(false)}}
 async function saveEntity(){const table=semanticTables.find(t=>`${t.schema_name}.${t.table_name}`===entity.table);if(!table)return;setBusy(true);try{const r=await fetch(API+"/api/admin/semantic/entities",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({source_name:form.name,name:entity.name,description:entity.description||null,schema_name:table.schema_name,table_name:table.table_name,key_column:entity.key_column,display_column:entity.display_column||null,synonyms:entity.synonyms.split(",").map(x=>x.trim()).filter(Boolean),attributes:entity.attributes.map(a=>({name:a.name,description:a.description||null,column_name:a.column_name,synonyms:a.synonyms.split(",").map(x=>x.trim()).filter(Boolean),operators:a.operators.length?a.operators:["="],value_mappings:a.value_mappings.split("\n").map(line=>line.trim()).filter(Boolean).map(line=>{const [canonical,...aliases]=line.split("|");return {canonical_value:canonical.trim(),synonyms:aliases.join("|").split(",").map(v=>v.trim()).filter(Boolean)}})}))})});const d=await r.json();if(!r.ok)throw new Error(d.detail||"Unable to save entity");setMessage(d.message);setEntity(emptyEntity());await loadSemantic()}catch(e){setMessage(e instanceof Error?e.message:"Unable to save entity")}finally{setBusy(false)}}
 return <div className="shell"><aside><div className="brand"><div className="mark">DP</div><div><strong>Data Pilot</strong><span>Admin Studio</span></div></div>
 <nav>{sections.map(([name,Icon])=><button className={active===name?"active":""} onClick={()=>{setActive(name);if(name==="AI Provider")loadAiConfig();if(name==="Semantic Model"){loadSemantic();loadDatasets()}if(name==="Metrics")loadMetrics();if(name==="Business Rules")loadRules();if(name==="Time Semantics")loadTimeDimensions();if(name==="Query Playground")loadQueryHistory()}} key={name}><Icon size={18}/>{name}</button>)}</nav><div className="asideFoot"><Settings2 size={17}/>Local development</div></aside>
 <main><header><div><p className="eyebrow">OPEN-SOURCE CORE</p><h1>{active}</h1></div><div className="status"><i/>{schemas.length?"Schema discovered":"Local configuration"}</div></header>
 <section className="intro"><h2>{sections.find(x=>x[0]===active)?.[2]}</h2><p>Configure and inspect Data Pilot without editing source code. Saved onboarding credentials are managed separately and never displayed. The connection test form uses local defaults; its name is not the active semantic datasource.</p></section>
 {savedSourceId!==null&&<p className="notice">Active saved datasource: <strong>{savedSourceName}</strong> · Discovered schema restored from onboarding. Credentials remain securely stored by the setup service.</p>}
 {sourceRestoreError&&<p className="notice">{sourceRestoreError}</p>}
 {active==="AI Provider"&&<section className="grid"><article className="wide"><h3>Saved AI provider</h3><p>Update the saved model or rotate its API key without repeating onboarding. Credentials are sent to the setup API and are never returned by read endpoints.</p><p>Credential: <strong>{aiConfig.credential_configured?"Available":"Missing — update required"}</strong> · Validation: <strong>{aiValidated===null?"Unknown":aiValidated?"Ready":"Not ready"}</strong></p><div className="semanticForm"><label>Provider<input value={aiConfig.provider} disabled readOnly/></label><label>Model<input value={aiConfig.model} onChange={e=>setAiConfig({...aiConfig,model:e.target.value})}/></label><label>Provider API key<input type="password" autoComplete="new-password" value={aiKey} onChange={e=>setAiKey(e.target.value)} placeholder="Leave blank to retain the saved key"/></label></div><div className="actions"><button className="primary" disabled={aiBusy||!aiConfig.model.trim()||(!aiConfig.credential_configured&&!aiKey.trim())} onClick={saveAiConfig}>{aiBusy?"Saving…":"Save AI provider"}</button><button className="secondary" disabled={aiBusy} onClick={loadAiConfig}>Refresh status</button></div>{aiMessage&&<p className="notice">{aiMessage}</p>}</article></section>}
 {active==="Data Sources"&&<section className="grid">{savedSourceId!==null&&<article className="wide"><h3>Saved datasource connection</h3><p><strong>{savedSourceName}</strong> — configuration stored securely. Password is never displayed.</p>{savedSourceDetails&&<p>Host: <strong>{savedSourceDetails.host}</strong> · Port: <strong>{savedSourceDetails.port}</strong> · Database: <strong>{savedSourceDetails.database}</strong> · Username: <strong>{savedSourceDetails.username}</strong> · SSL: <strong>{savedSourceDetails.sslmode}</strong></p>}<div className="actions"><button onClick={testSavedSource} disabled={savedSourceTesting}>{savedSourceTesting?"Testing…":"Test saved connection"}</button></div>{savedSourceTestMessage&&<p className="notice">{savedSourceTestMessage}</p>}<div className="semanticForm"><label>New datasource password<input type="password" autoComplete="new-password" value={newCredential} onChange={e=>setNewCredential(e.target.value)}/></label></div><div className="actions"><button disabled={!newCredential||credentialBusy} onClick={updateCredential}>{credentialBusy?"Validating…":"Validate and rotate password"}</button></div>{credentialStatus&&<p className="notice">{credentialStatus}</p>}<div className="semanticForm"><h4>Change database username and password</h4><p>Both values are required and validated together. Host and database remain unchanged.</p><label>New username<input value={newLoginUsername} onChange={e=>setNewLoginUsername(e.target.value)} placeholder="Database login"/></label><label>Password for new username<input type="password" autoComplete="new-password" value={newLoginPassword} onChange={e=>setNewLoginPassword(e.target.value)}/></label></div><div className="actions"><button disabled={loginBusy||!newLoginUsername.trim()||!newLoginPassword} onClick={updateSavedLogin}>{loginBusy?"Validating…":"Validate and update login"}</button></div>{loginStatus&&<p className="notice">{loginStatus}</p>}</article>}<article className="wide"><div className="cardTitle"><Database size={20}/><h3>PostgreSQL connection test</h3><span>Development</span></div>
 <div className="formGrid"><label>Name<input value={connectionTestName} onChange={e=>setConnectionTestName(e.target.value)}/></label><label>Host<input value={form.host} onChange={e=>update("host",e.target.value)}/></label>
 <label>Port<input type="number" value={form.port} onChange={e=>update("port",Number(e.target.value))}/></label><label>Database<input value={form.database} onChange={e=>update("database",e.target.value)}/></label>
 <label>Username<input value={form.username} onChange={e=>update("username",e.target.value)}/></label><label>Password<input type="password" value={form.password} onChange={e=>update("password",e.target.value)}/></label></div>
 <div className="actions"><button onClick={test} disabled={busy||!form.password}>Test connection</button><button className="primary" onClick={discover} disabled={busy||!form.password}>Discover schema</button></div>{message&&<p className="notice">{message}</p>}</article></section>}
 {active==="Schema Explorer"&&<section>{schemas.length===0?<article className="wide"><div className="empty">Connect a data source and run schema discovery first.</div></article>:schemas.map(s=><article className="schema" key={s.schema_name}><h3>{s.schema_name} <span>{s.tables.length} tables/views</span></h3>{s.tables.map(t=><details key={t.name}><summary>{t.name}<small>{t.columns.length} columns · {t.primary_keys.length} PK · {t.foreign_keys.length} FK</small></summary><div className="columns">{t.columns.map(c=><div className="schemaColumnEntry" key={c.name}><div className="schemaColumnRow"><code>{c.name}</code><span>{c.data_type}</span><span className="schemaColumnKey">{c.is_primary_key&&<b>PK</b>}</span><span className="schemaColumnAction">{savedSourceId!==null&&["text","character varying","character","varchar","char"].includes(c.data_type.toLowerCase())&&<button type="button" disabled={categoryBusy} onClick={()=>discoverCategory(s.schema_name||"",t.name,c.name)}>Discover values</button>}</span></div>{categoryProposal?.key===(s.schema_name+"."+t.name+"."+c.name)&&<div className="schemaColumnProposal">{categoryProposal.error?<p role="alert">{categoryProposal.error}</p>:<><strong>Discovered values ({categoryProposal.values.length}{categoryProposal.complete?" complete":" truncated"})</strong><p>Review exact database values, optionally add synonyms, then explicitly publish selected mappings to the configured semantic attribute.</p>{categoryProposal.values.map(v=><label className="categoryReviewRow" key={v}><input type="checkbox" checked={categoryReviewed.includes(v)} onChange={e=>setCategoryReviewed(prev=>e.target.checked?[...prev,v]:prev.filter(x=>x!==v))}/><code>{v}</code><input aria-label={"Synonyms for "+v} placeholder="Optional synonyms, comma separated" value={categoryAliases[v]||""} onChange={e=>setCategoryAliases(prev=>({...prev,[v]:e.target.value}))}/></label>)}<div className="categoryReviewActions"><button type="button" onClick={()=>setCategoryReviewed(categoryProposal.values)}>Select all</button><button type="button" onClick={()=>setCategoryReviewed([])}>Clear</button><button type="button" disabled={!categoryReviewed.length||!categoryProposal.complete||categoryBusy} onClick={publishCategoryMappings}>Publish selected mappings</button></div>{categoryReviewMessage&&<p role="status">{categoryReviewMessage}</p>}<textarea readOnly aria-label="Canonical mapping draft" rows={Math.min(8,Math.max(2,categoryReviewed.length))} value={categoryProposal.values.filter(v=>categoryReviewed.includes(v)).map(v=>v+" | "+(categoryAliases[v]||"")).join("\n")}/></>}</div>}</div>)}</div></details>)}</article>)}</section>}
 {active==="Semantic Model"&&<><section className="datasetSemantic"><article className="wide"><div className="sectionHeading"><div><h3>Dataset / View Info</h3><p>Describe what a physical dataset means before Data Pilot reasons over its entities, metrics and rules.</p></div><span>{datasets.length} configured</span></div>
 <div className="datasetPicker"><label>Physical dataset<select value={datasetKey} onChange={e=>selectDataset(e.target.value)}><option value="">Select table or view…</option>{semanticTables.map((t:any)=><option key={t.schema_name+"."+t.table_name} value={t.schema_name+"."+t.table_name}>{t.schema_name}.{t.table_name}</option>)}</select></label>{datasetKey&&<span className="configuredBadge">{datasets.some((d:any)=>d.schema_name+"."+d.table_name===datasetKey)?"Configured":"Not configured"}</span>}</div>
 {datasetKey?<><div className="datasetForm"><label className="full">Description<textarea value={dataset.description} onChange={e=>setDataset({...dataset,description:e.target.value})} placeholder="What does this table or view contain?"/></label>
 <label className="full">Business meaning<textarea value={dataset.business_meaning} onChange={e=>setDataset({...dataset,business_meaning:e.target.value})} placeholder="What business process or analytical concept does this dataset represent?"/></label>
 <label>Grain<textarea value={dataset.grain} onChange={e=>setDataset({...dataset,grain:e.target.value})} placeholder="One row represents…"/></label>
 <label>Identity semantics<textarea value={dataset.identity_semantics} onChange={e=>setDataset({...dataset,identity_semantics:e.target.value})} placeholder="How is a record uniquely identified?"/></label>
 <label className="full">Aliases<input value={dataset.aliases} onChange={e=>setDataset({...dataset,aliases:e.target.value})} placeholder="order lines, sales lines, order items"/></label>
 <label>Recommended use cases<textarea value={dataset.use_cases} onChange={e=>setDataset({...dataset,use_cases:e.target.value})} placeholder={"One use case per line\nRevenue by product\nUnits sold"}/></label>
 <label>Query constraints<textarea value={dataset.query_constraints} onChange={e=>setDataset({...dataset,query_constraints:e.target.value})} placeholder={"One constraint per line\nUse latest snapshot unless trend is requested"}/></label></div>
 <button className="primary" disabled={busy} onClick={saveDataset}>Save dataset semantics</button></>:<div className="empty">Select a discovered physical table or view to configure its dataset-level meaning.</div>}
 {message&&<p className="notice">{message}</p>}</article></section><section className="datasetSemantic"><article className="wide"><div className="sectionHeading"><div><h3>C5 · Semantic Bootstrap Preview</h3><p>Review schema-grounded suggestions. Existing entities, attributes and canonical value mappings are preserved; nothing is saved until you explicitly save the entity.</p></div></div>
 <div className="semanticForm"><label>Discovered table<select value={bootstrapTable} onChange={e=>{setBootstrapTable(e.target.value);setBootstrapPreview(null);setBootstrapSelected([]);setBootstrapMessage("");}}><option value="">Select table…</option>{semanticTables.map((t:any)=><option key={t.schema_name+"."+t.table_name} value={t.schema_name+"."+t.table_name}>{t.schema_name}.{t.table_name}</option>)}</select></label></div>
 <button type="button" className="secondary" disabled={bootstrapBusy||!bootstrapTable} onClick={previewBootstrap}>{bootstrapBusy?"Loading…":"Preview suggestions"}</button>
 {bootstrapPreview&&(()=>{const existing=entities.find((e:any)=>e.schema_name===bootstrapPreview.schema_name&&e.table_name===bootstrapPreview.table_name);
 const known=new Set((existing?.attributes||[]).map((a:any)=>a.column_name));
 const suggestions:any[]=bootstrapPreview.entity?.attributes||[];
 const available=suggestions.filter(a=>!known.has(a.column_name));
 const visible=suggestions.filter(a=>(bootstrapFilter==="all"||(bootstrapFilter==="new"?!known.has(a.column_name):known.has(a.column_name)))&&(!bootstrapSearch||[a.name,a.column_name,a.evidence?.data_type].join(" ").toLowerCase().includes(bootstrapSearch.toLowerCase())));
 return <div className="attributeEditor">
 <p>{suggestions.length} discovered · {known.size} configured · {available.length} new · {bootstrapSelected.length} selected · Not published</p>
 <div style={{display:"flex",gap:"8px",flexWrap:"wrap",alignItems:"center",marginBottom:"12px"}}>
 <input style={{flex:"1 1 230px"}} placeholder="Search column name or type…" value={bootstrapSearch} onChange={e=>setBootstrapSearch(e.target.value)}/>
 <select style={{flex:"0 1 200px"}} value={bootstrapFilter} onChange={e=>setBootstrapFilter(e.target.value as "new"|"all"|"existing")}><option value="new">New suggestions</option><option value="existing">Already configured</option><option value="all">All columns</option></select>
 <button type="button" className="secondary" onClick={()=>{setBootstrapSelected(available.map(a=>a.column_name));setBootstrapConfirmed(false);}}>Select all new</button>
 <button type="button" className="secondary" onClick={()=>{setBootstrapSelected([]);setBootstrapConfirmed(false);}}>Clear selection</button></div>
 <div className="attributeList" style={{maxHeight:"420px",overflowY:"auto"}}>{visible.map(a=>{const already=known.has(a.column_name);return <label key={a.column_name} className="attributeRow" style={{display:"flex",alignItems:"center",gap:"12px",justifyContent:"flex-start"}}>
 <input type="checkbox" style={{width:"auto",flex:"0 0 auto"}} disabled={already} checked={already||bootstrapSelected.includes(a.column_name)} onChange={e=>{setBootstrapSelected(current=>e.target.checked?[...current,a.column_name]:current.filter(x=>x!==a.column_name));setBootstrapConfirmed(false);}}/>
 <span style={{flex:"1",textAlign:"left"}}><strong>{a.name}</strong> · {a.column_name} ({a.evidence?.data_type||"unknown"}) {already?"— existing; protected":"— suggested"}</span></label>})}
 {!visible.length&&<p>No columns match this filter.</p>}</div>
 <label style={{display:"flex",alignItems:"center",gap:"8px",margin:"12px 0"}}><input type="checkbox" style={{width:"auto"}} checked={bootstrapConfirmed} disabled={!bootstrapSelected.length} onChange={e=>setBootstrapConfirmed(e.target.checked)}/>I reviewed these {bootstrapSelected.length} additions and understand they will be staged for manual saving.</label>
 <button type="button" className="secondary" disabled={!bootstrapConfirmed||!bootstrapSelected.length} onClick={stageBootstrap}>Stage {bootstrapSelected.length} reviewed attributes in editor</button></div>})()}
 {bootstrapMessage&&<p className="notice">{bootstrapMessage}</p>}</article></section>
 <section className="grid semanticGrid"><article><div className="sectionHeading"><h3>{entity.id?"Edit semantic entity":"Add semantic entity"}</h3>{entity.id&&<button className="secondary" onClick={()=>setEntity(emptyEntity())}>New entity</button>}</div><div className="semanticForm">
 <label>Business name<input value={entity.name} onChange={e=>setEntity({...entity,name:e.target.value})} placeholder="Product"/></label>
 <label>Description<textarea value={entity.description} onChange={e=>setEntity({...entity,description:e.target.value})}/></label>
 <label>Physical table<select value={entity.table} onChange={e=>setEntity({...entity,table:e.target.value,key_column:"",display_column:"",attributes:[]})}><option value="">Select table…</option>{semanticTables.map(t=><option key={t.schema_name+"."+t.table_name} value={t.schema_name+"."+t.table_name}>{t.schema_name}.{t.table_name}</option>)}</select></label>
 {(()=>{const t=semanticTables.find(x=>x.schema_name+"."+x.table_name===entity.table);const cols=t?.columns||[];return <><label>Key column<select value={entity.key_column} onChange={e=>setEntity({...entity,key_column:e.target.value})}><option value="">Select key…</option>{cols.map((x:any)=><option key={x.name} value={x.name}>{x.name}{x.is_primary_key?" (PK)":""}</option>)}</select></label>
 <label>Display column<select value={entity.display_column} onChange={e=>setEntity({...entity,display_column:e.target.value})}><option value="">None</option>{cols.map((x:any)=><option key={x.name} value={x.name}>{x.name}</option>)}</select></label></>})()}
 <label>Synonyms<input value={entity.synonyms} onChange={e=>setEntity({...entity,synonyms:e.target.value})} placeholder="product, item, SKU"/></label></div>
 {entity.table&&<div id="semantic-attribute-form" className="attributeEditor"><div className="attributeTitle"><div><h4>Attributes</h4><p>Map business fields to physical columns.</p></div><span>{entity.attributes.length} configured</span></div>
 {entity.attributes.length>0&&<div className="attributeList">{entity.attributes.map((a,i)=><div className="attributeRow" key={a.name+"-"+i}><div><strong>{a.name}</strong><span>→ {a.column_name}</span><small>{a.synonyms||"No synonyms"} · {a.operators.join(" ")}</small></div><div className="actions"><button type="button" className="secondary" onClick={()=>editAttribute(i)}>Edit</button><button type="button" onClick={()=>removeAttribute(i)}>Remove</button></div></div>)}</div>}
 <div className="attributeForm"><label>Business name<input value={attribute.name} onChange={e=>setAttribute({...attribute,name:e.target.value})} placeholder="e.g. Ownership Status"/></label>
 <label>Physical column<select value={attribute.column_name} onChange={e=>setAttribute({...attribute,column_name:e.target.value})}><option value="">Select column…</option>{(semanticTables.find(t=>t.schema_name+"."+t.table_name===entity.table)?.columns||[]).map((x:any)=><option key={x.name} value={x.name}>{x.name} · {x.data_type}</option>)}</select></label>
 <label className="full">Description<input value={attribute.description} onChange={e=>setAttribute({...attribute,description:e.target.value})} placeholder="Describe what this field represents"/></label>
 <label className="full">Synonyms<input value={attribute.synonyms} onChange={e=>setAttribute({...attribute,synonyms:e.target.value})} placeholder="Alternative names, comma separated"/></label>
 <label className="full">Canonical values and synonyms (one per line: database value | user expressions)<textarea rows={10} style={{minHeight:"220px",resize:"vertical",fontFamily:"ui-monospace, SFMono-Regular, Consolas, monospace",lineHeight:1.5}} value={attribute.value_mappings} onChange={e=>setAttribute({...attribute,value_mappings:e.target.value})} placeholder={"ON ORDER | on order, ordered\nDELIVERED | delivered"}/></label><div className="full"><span className="fieldLabel">Allowed operators</span><div className="operatorChoices">{["=",">",">=","<","<=","!="].map(op=><button type="button" className={attribute.operators.includes(op)?"selected":""} onClick={()=>toggleOperator(op)} key={op}>{op}</button>)}</div></div>
 <button className="secondary full" disabled={!attribute.name||!attribute.column_name} onClick={addAttribute}>{editingAttributeIndex===null?"+ Add attribute":"Update attribute"}</button>{editingAttributeIndex!==null&&<button type="button" className="secondary full" onClick={cancelAttributeEdit}>Cancel editing</button>}</div></div>}
 <button className="primary" disabled={busy||!entity.name||!entity.table||!entity.key_column} onClick={saveEntity}>{entity.id?"Save changes":"Save entity"}</button>{message&&<p className="notice">{message}</p>}</article>
 <article><h3>Configured entities</h3>{entities.length===0?<div className="empty">No semantic entities yet.</div>:entities.map(e=><button className={"entityCard entityButton "+(entity.id===e.id?"selectedEntity":"")} key={e.id} onClick={()=>editEntity(e)}><strong>{e.name}</strong><span>{e.schema_name}.{e.table_name}</span><p>{e.description||"No description"}</p><small>{e.synonyms.length?e.synonyms.join(", "):"No synonyms"}</small><em>{e.attributes?.length||0} attributes · Click to edit</em></button>)}</article>
 <article className="wide relationshipPanel"><div className="attributeTitle"><div><h4>Relationships</h4><p>Teach Data Pilot how semantic entities join across physical tables.</p></div><span>{relationships.length} configured</span></div>
 <div className="relationshipForm"><label>Name<input value={relationship.name} onChange={e=>setRelationship({...relationship,name:e.target.value})} placeholder="Sales Order Line to Product"/></label>
 <label>Cardinality<select value={relationship.cardinality} onChange={e=>setRelationship({...relationship,cardinality:e.target.value})}><option value="one-to-one">one-to-one</option><option value="one-to-many">one-to-many</option><option value="many-to-one">many-to-one</option><option value="many-to-many">many-to-many</option></select></label>
 <label>From entity<select value={relationship.from_entity_id} onChange={e=>setRelationship({...relationship,from_entity_id:e.target.value,from_column:""})}><option value="">Select entity…</option>{entities.map(e=><option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
 <label>From column<select value={relationship.from_column} onChange={e=>setRelationship({...relationship,from_column:e.target.value})}><option value="">Select column…</option>{(()=>{const en=entities.find(x=>String(x.id)===relationship.from_entity_id);const t=semanticTables.find(x=>en&&x.schema_name===en.schema_name&&x.table_name===en.table_name);return (t?.columns||[]).map((x:any)=><option key={x.name} value={x.name}>{x.name}</option>)})()}</select></label>
 <label>To entity<select value={relationship.to_entity_id} onChange={e=>setRelationship({...relationship,to_entity_id:e.target.value,to_column:""})}><option value="">Select entity…</option>{entities.map(e=><option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
 <label>To column<select value={relationship.to_column} onChange={e=>setRelationship({...relationship,to_column:e.target.value})}><option value="">Select column…</option>{(()=>{const en=entities.find(x=>String(x.id)===relationship.to_entity_id);const t=semanticTables.find(x=>en&&x.schema_name===en.schema_name&&x.table_name===en.table_name);return (t?.columns||[]).map((x:any)=><option key={x.name} value={x.name}>{x.name}</option>)})()}</select></label>
 <label className="full">Description<input value={relationship.description} onChange={e=>setRelationship({...relationship,description:e.target.value})} placeholder="Each sales order line references one product"/></label>
 <button className="primary full" disabled={busy||!relationship.name||!relationship.from_entity_id||!relationship.from_column||!relationship.to_entity_id||!relationship.to_column||relationship.from_entity_id===relationship.to_entity_id} onClick={saveRelationship}>Save relationship</button></div>
 {relationships.length>0&&<div className="relationshipList">{relationships.map(r=><div className="relationshipRow" key={r.id}><strong>{r.name}</strong><span>{r.from_entity_name}.{r.from_column} → {r.to_entity_name}.{r.to_column}</span><small>{r.cardinality}{r.description?" · "+r.description:""}</small></div>)}</div>}</article></section></>}
 {active==="Metrics"&&<section className="grid"><article><h3>{metric.id?"Edit metric":"Define metric"}</h3><div className="semanticForm">
 <label>Name<input value={metric.name} onChange={e=>setMetric({...metric,name:e.target.value})} placeholder="Revenue"/></label>
 <label>Description<textarea value={metric.description} onChange={e=>setMetric({...metric,description:e.target.value})} placeholder="Total sales revenue"/></label>
 <label>Base entity<select value={metric.entity_id} onChange={e=>setMetric({...metric,entity_id:e.target.value,attribute_name:"",calculation_expression:""})}><option value="">Select entity…</option>{metricEntities.map(e=><option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
 <label>Metric type<select value={metric.metric_type} onChange={e=>setMetric({...metric,metric_type:e.target.value,attribute_name:"",calculation_expression:""})}><option value="simple">Simple attribute metric</option><option value="derived">Calculated / derived metric</option></select></label>
 {metric.metric_type==="simple"?<label>Attribute<select value={metric.attribute_name} onChange={e=>setMetric({...metric,attribute_name:e.target.value})}><option value="">Select semantic attribute…</option>{(metricEntities.find(e=>String(e.id)===metric.entity_id)?.attributes||[]).map((a:any)=><option key={a.name} value={a.name}>{a.name} → {a.column_name}</option>)}</select></label>:<label className="full">Calculation expression<input value={metric.calculation_expression} onChange={e=>setMetric({...metric,calculation_expression:e.target.value})} placeholder="OrderQty * UnitPrice * (1 - UnitPriceDiscount)"/><small>Use physical columns exposed as attributes on the selected entity. Data Pilot validates the expression before saving.</small></label>}
 <label>Aggregation<select value={metric.aggregation} onChange={e=>setMetric({...metric,aggregation:e.target.value})}><option value="sum">SUM</option><option value="count">COUNT</option><option value="count_distinct">COUNT DISTINCT</option><option value="avg">AVG</option><option value="min">MIN</option><option value="max">MAX</option></select></label>
 <label>Format<select value={metric.format} onChange={e=>setMetric({...metric,format:e.target.value})}><option value="number">Number</option><option value="integer">Integer</option><option value="currency">Currency</option><option value="percent">Percent</option></select></label>
 <label>Synonyms<input value={metric.synonyms} onChange={e=>setMetric({...metric,synonyms:e.target.value})} placeholder="revenue, sales, total sales"/></label></div>
 <button className="primary" disabled={busy||!metric.name||!metric.entity_id||(metric.metric_type==="simple"?!metric.attribute_name:!metric.calculation_expression.trim())} onClick={saveMetric}>{metric.id?"Update metric":"Save metric"}</button>{metric.id&&<button className="secondary" disabled={busy} onClick={cancelMetricEdit}>Cancel edit</button>}{message&&<p className="notice">{message}</p>}</article>
 <article><h3>Configured metrics</h3>{metrics.length===0?<div className="empty">No metrics yet.</div>:metrics.map(m=><div className={"entityCard "+(metric.id===m.id?"selectedEntity":"")} key={m.id}><strong>{m.name}</strong><span>{m.metric_type==="derived"?m.aggregation.replace("_"," ").toUpperCase()+"("+m.calculation_expression+")":m.aggregation.replace("_"," ").toUpperCase()+"("+m.entity_name+"."+m.attribute_name+")"}</span><p>{m.description||"No description"}</p><small>{m.synonyms.length?m.synonyms.join(", "):"No synonyms"} · {m.format}</small><button className="secondary" onClick={()=>editMetric(m)}>Edit</button></div>)}</article></section>}
 {active==="Business Rules"&&<section className="grid"><article><h3>{rule.id?"Edit business rule":"Define business rule"}</h3><div className="semanticForm">
 <label>Name<input value={rule.name} onChange={e=>setRule({...rule,name:e.target.value})} placeholder="Revenue excludes cancelled orders"/></label>
 <label>Definition<textarea value={rule.description} onChange={e=>setRule({...rule,description:e.target.value})} placeholder="Describe the governed business meaning or constraint in natural language."/></label>
 <label>Rule type<select value={rule.rule_type} onChange={e=>setRule({...rule,rule_type:e.target.value})}><option value="definition">Definition</option><option value="filter">Filter</option><option value="calculation">Calculation</option><option value="interpretation">Interpretation</option></select></label>
 <label>Target type<select value={rule.target_type} onChange={e=>setRule({...rule,target_type:e.target.value,entity_id:"",metric_id:""})}><option value="entity">Entity</option><option value="metric">Metric</option></select></label>
 {rule.target_type==="entity"?<label>Target entity<select value={rule.entity_id} onChange={e=>setRule({...rule,entity_id:e.target.value})}><option value="">Select entity…</option>{ruleEntities.map(e=><option key={e.id} value={e.id}>{e.name}</option>)}</select></label>:<label>Target metric<select value={rule.metric_id} onChange={e=>setRule({...rule,metric_id:e.target.value})}><option value="">Select metric…</option>{ruleMetrics.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label>}
 <label>Priority<input type="number" min="1" max="1000" value={rule.priority} onChange={e=>setRule({...rule,priority:Number(e.target.value)})}/></label>
 <label>Keywords<input value={rule.keywords} onChange={e=>setRule({...rule,keywords:e.target.value})} placeholder="cancelled, revenue, sales"/></label>
 <label className="checkLabel"><input type="checkbox" checked={rule.enabled} onChange={e=>setRule({...rule,enabled:e.target.checked})}/> Enabled</label></div>
 <button className="primary" disabled={busy||!rule.name||!rule.description||(rule.target_type==="entity"?!rule.entity_id:!rule.metric_id)} onClick={saveRule}>{rule.id?"Update business rule":"Save business rule"}</button>{rule.id&&<button className="secondary" disabled={busy} onClick={cancelRuleEdit}>Cancel edit</button>}{message&&<p className="notice">{message}</p>}</article>
 <article><h3>Configured rules</h3>{rules.length===0?<div className="empty">No business rules yet.</div>:rules.map(r=><div className={"entityCard "+(rule.id===r.id?"selectedEntity":"")} key={r.id}><strong>{r.name}</strong><span>{r.rule_type} · {r.entity_name||r.metric_name} · priority {r.priority}</span><p>{r.description}</p><small>{r.keywords.length?r.keywords.join(", "):"No keywords"} · {r.enabled?"enabled":"disabled"}</small><button className="secondary" onClick={()=>editRule(r)}>Edit</button></div>)}</article></section>}
 {active==="Time Semantics"&&<section className="grid"><article><h3>{timeDimension.id?"Edit time dimension":"Define time dimension"}</h3><p>Map business date roles to governed semantic attributes. Relative phrases are resolved deterministically before SQL generation.</p><div className="semanticForm">
 <label>Name<input value={timeDimension.name} onChange={e=>setTimeDimension({...timeDimension,name:e.target.value})} placeholder="Order Date"/></label>
 <label>Entity<select value={timeDimension.entity_id} onChange={e=>setTimeDimension({...timeDimension,entity_id:e.target.value,column_name:""})}><option value="">Select entity…</option>{timeEntities.map(e=><option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
 <label>Date/time attribute<select value={timeDimension.column_name} onChange={e=>setTimeDimension({...timeDimension,column_name:e.target.value})}><option value="">Select semantic attribute…</option>{(timeEntities.find(e=>String(e.id)===timeDimension.entity_id)?.attributes||[]).map((a:any)=><option key={a.column_name} value={a.column_name}>{a.name} → {a.column_name}</option>)}</select></label>
 <label>Role<input value={timeDimension.role} onChange={e=>setTimeDimension({...timeDimension,role:e.target.value})} placeholder="order_date"/></label>
 <label>Grain<select value={timeDimension.grain} onChange={e=>setTimeDimension({...timeDimension,grain:e.target.value})}><option value="date">Date</option><option value="day">Day</option><option value="week">Week</option><option value="month">Month</option><option value="quarter">Quarter</option><option value="year">Year</option><option value="timestamp">Timestamp</option></select></label>
 <label>Timezone<input value={timeDimension.timezone} onChange={e=>setTimeDimension({...timeDimension,timezone:e.target.value})} placeholder="UTC"/></label>
 <label className="full">Synonyms<input value={timeDimension.synonyms} onChange={e=>setTimeDimension({...timeDimension,synonyms:e.target.value})} placeholder="ordered, sale date, order date"/></label>
 <label className="checkLabel"><input type="checkbox" checked={timeDimension.is_default} onChange={e=>setTimeDimension({...timeDimension,is_default:e.target.checked})}/> Default date role for this entity</label></div>
 <button className="primary" disabled={busy||!timeDimension.name||!timeDimension.entity_id||!timeDimension.column_name||!timeDimension.role||!timeDimension.timezone} onClick={saveTimeDimension}>{timeDimension.id?"Update time dimension":"Save time dimension"}</button>{timeDimension.id&&<button className="secondary" disabled={busy} onClick={cancelTimeEdit}>Cancel edit</button>}{message&&<p className="notice">{message}</p>}</article>
 <article><h3>Configured time dimensions</h3>{timeDimensions.length===0?<div className="empty">No governed time dimensions yet.</div>:timeDimensions.map(t=><div className={"entityCard "+(timeDimension.id===t.id?"selectedEntity":"")} key={t.id}><strong>{t.name}</strong><span>{t.entity_name}.{t.column_name} · {t.role}</span><p>{t.grain} · {t.timezone}{t.is_default?" · default":""}</p><small>{t.synonyms?.length?t.synonyms.join(", "):"No synonyms"}</small><button className="secondary" onClick={()=>editTimeDimension(t)}>Edit</button></div>)}</article></section>}
 {active==="Query Playground"&&<section className="queryPlayground"><div className="playgroundTabs"><button className={playgroundTab==="query"?"active":""} onClick={()=>setPlaygroundTab("query")}>New query</button><button className={playgroundTab==="history"?"active":""} onClick={()=>{setPlaygroundTab("history");loadQueryHistory()}}>History <span>{queryHistory.length}</span></button></div>{playgroundTab==="query"?<><article className="askPanel"><div className="sectionHeading"><div><h3>Ask Data Pilot</h3><p>Run one question at a time. Previous runs stay in History instead of growing this workspace.</p></div></div>{followUpTo&&<div className="historySnapshot"><div><strong>Follow-up context</strong><span>Continuing from query #{followUpTo.id}</span><p>{followUpTo.question}</p><small>Data Pilot carries forward governed semantic lineage, not prior SQL. This turn is retrieved, generated and validated again.</small></div><button className="secondary" onClick={startNewQuery}>Clear context</button></div>}<div className="semanticForm"><label>{followUpTo?"Follow-up question":"Question"}<textarea value={queryQuestion} onChange={e=>setQueryQuestion(e.target.value)} placeholder={followUpTo?"Only red products":"Show revenue by product"}/></label></div><div className="actions"><button className="secondary" disabled={busy||!queryQuestion.trim()} onClick={()=>runQuery(true)}>{busy?"Working…":"Dry run"}</button><button className="primary" disabled={busy||!queryQuestion.trim()} onClick={()=>runQuery(false)}>{busy?"Running…":"Run query"}</button></div>{message&&<p className="notice">{message}</p>}</article> {queryResponse&&<>{queryResponse.status==="ambiguous"&&queryResponse.clarification&&<article className="historySnapshot"><div><strong>Clarification needed</strong><span>{queryResponse.clarification.question}</span><p>{queryResponse.message}</p><small>Data Pilot will not generate SQL until you choose a governed interpretation.</small></div><div className="historyActions">{(queryResponse.clarification.options||[]).map((option:any)=><button key={option.value} className="secondary" disabled={busy} title={option.description||""} onClick={()=>runQuery(false,{[queryResponse.clarification.key]:option.value})}>{option.label}</button>)}</div></article>}{selectedHistory&&<article className="historySnapshot"><div><strong>Historical trace #{selectedHistory.id}</strong><span>Saved {new Date(selectedHistory.created_at).toLocaleString()} · {selectedHistory.dry_run?"dry run":"executed"} · {selectedHistory.source_name||"unknown source"}</span><p>This is the exact persisted response and diagnostic trace from that run. Re-running uses the current semantic model, retrieval index and LLM configuration, so the new result may differ.</p></div><div className="historyActions"><button className="secondary" disabled={busy} onClick={()=>runQuery(true)}>Re-run as dry run</button><button className="primary" disabled={busy} onClick={()=>runQuery(false)}>Re-run query</button><button className="secondary" onClick={continueFromResult}>Continue from this result</button><button className="secondary" onClick={()=>{setSelectedHistory(null);setQueryResponse(null)}}>Close history</button></div></article>}<article className="tracePanel"><div className="sectionHeading"><div><h3>Query Trace</h3><p>Explain how Data Pilot moved from the question to executable SQL.</p></div><span>{queryResponse.status}</span></div>{queryResponse.trace?<div className="traceGrid">
 <div className="traceStep"><b>1</b><div><strong>Semantic boundary</strong><p>Datasets: {(queryResponse.trace.governed_datasets||[]).join(", ")||"—"}</p><p>Entities: {(queryResponse.trace.governed_entities||[]).join(", ")||"—"}</p><p>Relationships: {(queryResponse.trace.governed_relationships||[]).join(", ")||"—"}</p></div></div>
 <div className="traceStep"><b>2</b><div><strong>Business semantics</strong><p>Metrics: {(queryResponse.trace.governed_metrics||[]).join(", ")||"—"}</p><p>Rules: {(queryResponse.trace.governed_business_rules||[]).join(", ")||"—"}</p><p>Time roles: {(queryResponse.trace.governed_time_dimensions||[]).join(", ")||"—"}</p>{queryResponse.trace.time_interpretation?.status==="resolved"&&<details><summary>Time interpretation</summary><pre>{JSON.stringify(queryResponse.trace.time_interpretation,null,2)}</pre></details>}</div></div>
 <div className="traceStep"><b>3</b><div><strong>Physical context</strong><p>{(queryResponse.trace.physical_tables||[]).join(", ")||"—"}</p><details><summary>Columns</summary><pre>{JSON.stringify(queryResponse.trace.physical_columns||{},null,2)}</pre></details></div></div>
 <div className="traceStep"><b>4</b><div><strong>Resolved parameters</strong><pre>{JSON.stringify(queryResponse.trace.resolved_parameters||{},null,2)}</pre></div></div>
 <div className="traceStep"><b>5</b><div><strong>Context budget</strong><pre>{JSON.stringify(queryResponse.trace.context_budget||{},null,2)}</pre></div></div>
 <div className="traceStep"><b>6</b><div><strong>LLM prompt</strong><p>Exact messages sent to the SQL-generation model after context budgeting.</p><details><summary>Show full prompt</summary>{(queryResponse.trace.llm_messages||[]).map((m:any,i:number)=><div key={m.role+"-"+i}><small>{String(m.role).toUpperCase()}</small><pre>{m.content}</pre></div>)}</details></div></div>
 <div className="traceStep"><b>7</b><div><strong>SQL pipeline</strong><small>Generated</small><pre>{queryResponse.trace.generated_sql||"—"}</pre><small>Identifier-bound</small><pre>{queryResponse.trace.bound_sql||"—"}</pre><small>Validated</small><pre>{queryResponse.trace.validated_sql||"—"}</pre><small>Policy-approved</small><pre>{queryResponse.trace.policy_sql||"—"}</pre></div></div>
 <div className="traceStep"><b>8</b><div><strong>Safety & correctness</strong><p>Affected tables: {(queryResponse.trace.validation_affected_tables||[]).join(", ")||"—"}</p><p>Validation: {(queryResponse.trace.validation_warnings||[]).join(" · ")||"passed"}</p><p>Correctness: {(queryResponse.trace.correctness_checks||[]).map((x:any)=>`${x.status}: ${x.message}`).join(" · ")||"not checked"}</p><p>Policy: {(queryResponse.trace.policy_warnings||[]).join(" · ")||"passed"}</p></div></div>
 <div className="traceStep"><b>9</b><div><strong>Execution</strong>{queryResponse.trace.execution?.executed===false?<p>Skipped — dry run did not execute SQL against the source database.</p>:<p>{queryResponse.trace.execution?.row_count??0} rows · {Number(queryResponse.trace.execution?.execution_time_ms||0).toFixed(1)} ms</p>}</div></div>
 {queryResponse.trace.conversation_context?.parent_history_id&&<div className="traceStep traceWide"><b>↳</b><div><strong>Follow-up lineage</strong><p>Parent query #{queryResponse.trace.conversation_context.parent_history_id}: {queryResponse.trace.conversation_context.previous_question}</p><p>Prior governed metrics: {(queryResponse.trace.conversation_context.governed_metrics||[]).join(", ")||"—"} · entities: {(queryResponse.trace.conversation_context.governed_entities||[]).join(", ")||"—"}</p><small>Prior SQL is not reused.</small></div></div>}<div className="traceStep traceWide"><b>10</b><div><strong>Retrieval diagnostics</strong><p>Raw Qdrant candidates captured for this run. Similarity score helps retrieval; governed selection remains authoritative.</p><details><summary>Show {(queryResponse.trace.retrieved_candidates||[]).length} candidates</summary><div className="candidateTable">{(queryResponse.trace.retrieved_candidates||[]).map((r:any,i:number)=><div className="candidateRow" key={(r.stage||"")+"-"+(r.kind||"")+"-"+(r.name||"")+"-"+i}><span>{r.stage||queryResponse.trace.retrieval_stage||"retrieval"}</span><strong>{r.name||r.key||"Unnamed"}</strong><span>{String(r.kind||"unknown").replace("_"," ")}</span><code>{Number(r.score||0).toFixed(3)}</code><em className={r.decision==="selected"?"selectedDecision":"rejectedDecision"}>{r.decision||"unclassified"}</em></div>)}</div></details></div></div>
 </div>:<div className="empty">No structured trace returned.</div>}</article>
 <div className="queryDiagnostics"><article className="contextPanel"><div className="sectionHeading"><h3>Retrieved semantic context</h3><span>{(queryResponse.retrieved_context||[]).length} items</span></div><div className="contextList">{(queryResponse.retrieved_context||[]).map((x:any,i:number)=><div className="contextCard" key={x.kind+"-"+x.key+"-"+i}><strong>{x.name}</strong>{(()=>{const d=(queryResponse.trace?.retrieved_candidates||[]).find((r:any)=>r.kind===x.kind&&r.name===x.name);return <span>{x.kind.replace("_"," ")} · score {Number(x.score||0).toFixed(3)} · {d?.decision||"unclassified"}</span>})()}<p>{x.text}</p></div>)}</div></article><article className="sqlPanel"><div className="sectionHeading"><h3>Executable SQL</h3><span>{queryResponse.status}</span></div><pre className="sqlBlock">{queryResponse.sql||"No SQL generated"}</pre><div className={"validationStatus "+(queryResponse.validation_warnings?.length?"warning":"success")}><strong>{queryResponse.validation_warnings?.length?"Validation warnings":"Validation passed"}</strong><span>{queryResponse.validation_warnings?.length?queryResponse.validation_warnings.join(" · "):"SQL passed safety and execution policy checks."}</span></div></article></div>
 <article className="resultPanel"><div className="resultHeader"><div><h3>Result</h3><p>{queryResponse.result?.row_count??0} rows · {Number(queryResponse.result?.execution_time_ms||0).toFixed(1)} ms</p></div><div className="historyActions">{queryResponse.status==="completed"&&<button className="secondary" onClick={continueFromResult}>Continue from this result</button>}{queryResponse.presentation&&<span className="presentationBadge">{queryResponse.presentation.kind} · {queryResponse.presentation.recommended_visual}</span>}</div></div>{queryResponse.result_summary?.text&&<div className="answerSummary"><small>ANSWER</small><strong>{queryResponse.result_summary.text}</strong><span>Derived only from the returned result.</span>{queryResponse.result_summary.insights?.length>0&&<div className="insightStrip">{queryResponse.result_summary.insights.map((item:any,index:number)=><div className="insightCard" key={`${item.type}-${index}`}><small>{String(item.type||"insight").replaceAll("_"," ")}</small><strong>{item.label!=null?String(item.label):item.direction||item.measure||"Insight"}</strong>{item.share_percent!=null?<span>{displayValue(item.share_percent)}% of returned total</span>:item.value!=null?<span>{displayValue(item.value)}{item.measure?` · ${item.measure}`:""}</span>:item.direction?<span>{item.direction}</span>:null}</div>)}</div>}{queryResponse.result_summary.quality&&<div className={`resultDiagnostic ${queryResponse.result_summary.quality.status==="good"?"info":queryResponse.result_summary.quality.status==="partial"?"info":"warning"}`}><b>Result quality · {queryResponse.result_summary.quality.status}</b><span>{queryResponse.result_summary.quality.reason}</span></div>}{queryResponse.result_summary.diagnostics?.map((item:any,index:number)=><div key={`${item.code}-${index}`} className={`resultDiagnostic ${item.severity||"info"}`}><b>{item.severity==="warning"?"Data warning":"Data note"}</b><span>{item.message}</span></div>)}</div>}<ResultVisualization response={queryResponse}/>{queryResponse.result?.columns?.length?<details className="rawResult" open={!queryResponse.presentation||queryResponse.presentation.recommended_visual==="table"}><summary>Raw result table</summary><div className="resultTableWrap"><table className="resultTable"><thead><tr>{queryResponse.result.columns.map((col:string)=><th key={col}>{col}</th>)}</tr></thead><tbody>{([...((queryResponse.result.rows||[]) as any[][])].sort((a:any[],b:any[])=>{const p=queryResponse.presentation;if(p?.kind!=="comparison"||!queryResponse.result?.columns?.length)return 0;const cols=queryResponse.result.columns as string[];const dimensions=cols.map((_:string,i:number)=>i).filter((i:number)=>[...a,...b].some(()=>typeof a[i]==="string"&&isNaN(Number(a[i]))||typeof b[i]==="string"&&isNaN(Number(b[i]))));for(const i of dimensions){const cmp=String(a[i]??"").localeCompare(String(b[i]??""),undefined,{numeric:true});if(cmp)return cmp;}return 0;})).map((row:any[],ri:number)=><tr key={ri}>{row.map((value:any,ci:number)=><td key={ci} className={value===null?"nullCell":""}>{value===null?"NULL":String(value)}</td>)}</tr>)}</tbody></table></div></details>:<div className="empty">Query returned no columns.</div>}</article></>}</>:<div className="historyTab"><article className="wide"><div className="sectionHeading"><div><h3>Query History</h3><p>Recent persisted questions, SQL and semantic lineage for this data source.</p></div><button className="secondary" disabled={busy} onClick={loadQueryHistory}>Refresh</button></div>{queryHistory.length===0?<div className="empty">No query history yet. Run or dry-run a query to create the first entry.</div>:<div className="relationshipList">{queryHistory.map((h:any)=><button className="entityCard entityButton" key={h.id} onClick={()=>openQueryHistory(h.id)}><strong>{h.question}</strong><span>{h.status} · {h.dry_run?"dry run":"executed"} · {new Date(h.created_at).toLocaleString()}</span><p>{h.sql||"No SQL generated"}</p><small>{(h.governed_metrics||[]).length?"Metrics: "+h.governed_metrics.join(", "):"No governed metrics"}{h.row_count!=null?" · "+h.row_count+" rows":""}</small><em>Open saved trace</em></button>)}</div>}</article></div>}</section>}
 {!["Data Sources","AI Provider","Schema Explorer","Semantic Model","Metrics","Business Rules","Time Semantics","Query Playground"].includes(active)&&<section className="grid"><article className="wide"><h3>{active} foundation</h3><p>This is the next configuration surface after data-source discovery.</p><div className="empty">No configuration has been created yet.</div></article></section>}
 </main></div>
}