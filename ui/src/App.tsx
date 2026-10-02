import {useState} from "react";
import {Database, Network, BookOpen, Gauge, ShieldCheck, MessageSquareText, Settings2} from "lucide-react";

const sections=[
  ["Data Sources",Database,"Connect and test databases"],
  ["Schema Explorer",Network,"Inspect tables, columns and relationships"],
  ["Semantic Model",BookOpen,"Define entities, attributes and synonyms"],
  ["Metrics",Gauge,"Define reusable business metrics"],
  ["Business Rules",ShieldCheck,"Manage governed business definitions"],
  ["Query Playground",MessageSquareText,"Inspect NL-to-SQL execution"],
] as const;

export function App(){
 const [active,setActive]=useState("Data Sources");
 return <div className="shell">
  <aside>
   <div className="brand"><div className="mark">DP</div><div><strong>Data Pilot</strong><span>Admin Studio</span></div></div>
   <nav>{sections.map(([name,Icon])=><button className={active===name?"active":""} onClick={()=>setActive(name)} key={name}><Icon size={18}/>{name}</button>)}</nav>
   <div className="asideFoot"><Settings2 size={17}/>Local development</div>
  </aside>
  <main>
   <header><div><p className="eyebrow">OPEN-SOURCE CORE</p><h1>{active}</h1></div><div className="status"><i/>API configuration pending</div></header>
   <section className="intro">
    <h2>{sections.find(x=>x[0]===active)?.[2]}</h2>
    <p>This workspace is the configuration surface for Data Pilot. PostgreSQL remains the authoritative catalog; vector retrieval is an auxiliary capability.</p>
   </section>
   <section className="grid">
    {active==="Data Sources"?<>
      <article><div className="cardTitle"><Database size={20}/><h3>PostgreSQL</h3><span>Planned</span></div><p>Register a database, test connectivity, then discover its schema.</p><button className="primary">Add data source</button></article>
      <article><h3>Connection workflow</h3><ol><li>Enter connection details</li><li>Test connection</li><li>Discover schema</li><li>Review included objects</li></ol></article>
    </>:<article className="wide"><h3>{active} foundation</h3><p>The navigation and workspace are ready. The next implementation connects this screen to the corresponding FastAPI configuration endpoints.</p><div className="empty">No configuration has been created yet.</div></article>}
   </section>
  </main>
 </div>
}