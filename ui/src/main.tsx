import React,{useEffect,useState} from "react";
import ReactDOM from "react-dom/client";
import {App} from "./App";
import {Onboarding} from "./Onboarding";
import "./styles.css";

function Root(){
 const [mode,setMode]=useState<"loading"|"setup"|"app"|"error">("loading");
 useEffect(()=>{
  fetch("/api/setup/status").then(async response=>{
   if(!response.ok)throw new Error("Setup API unavailable");
   const data=await response.json();
   setMode(data.ready?"app":"setup");
  }).catch(()=>setMode("error"));
 },[]);
 if(mode==="loading")return <div className="onboardingPage"><p>Loading Data Pilot…</p></div>;
 if(mode==="error")return <div className="onboardingPage"><div className="onboardingCard"><h1>Unable to reach Data Pilot</h1><p>Check the API container and reload this page.</p><button onClick={()=>window.location.reload()}>Retry</button></div></div>;
 return mode==="setup"?<Onboarding onReady={()=>setMode("app")}/>:<App/>;
}
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><Root/></React.StrictMode>);
