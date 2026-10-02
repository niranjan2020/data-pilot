import React, { useState } from 'react';
import {
  Terminal,
  Database,
  Cpu,
  Layers,
  ShieldCheck,
  CheckCircle2,
  FileCode2,
  Server,
  BookOpen,
  ArrowRight,
  Code2,
  Activity,
  Boxes,
  HelpCircle,
  Copy,
  Check
} from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<'architecture' | 'interfaces' | 'endpoints' | 'quickstart'>('architecture');
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedCmd(id);
    setTimeout(() => setCopiedCmd(null), 2000);
  };

  const interfaces = [
    {
      name: 'LLMProvider',
      path: 'src/datapilot/domain/interfaces/llm.py',
      description: 'Pluggable AI provider abstraction (Gemini, OpenAI, Anthropic, or local open-weights).',
      methods: [
        'generate(messages, temperature, max_tokens, ...) -> LLMResponse',
        'generate_structured(messages, response_schema, ...) -> T',
      ],
      tag: 'AI-Agnostic'
    },
    {
      name: 'DatabaseProvider',
      path: 'src/datapilot/domain/interfaces/database.py',
      description: 'Abstract query executor and metadata introspector (PostgreSQL, Snowflake, MySQL, etc.).',
      methods: [
        'ping() -> bool',
        'introspect_schema(schema_name) -> SchemaMetadata',
        'execute_query(sql, params, timeout) -> QueryResult',
        'close() -> None',
      ],
      tag: 'DB-Agnostic'
    },
    {
      name: 'MetadataProvider',
      path: 'src/datapilot/domain/interfaces/metadata.py',
      description: 'Business catalog repository for table descriptions, semantic metrics, and entity synonyms.',
      methods: [
        'get_schema(schema_name) -> Optional[SchemaMetadata]',
        'save_schema(schema) -> None',
        'get_table(table_name, schema_name) -> Optional[TableMetadata]',
        'list_tables(schema_name) -> List[str]',
      ],
      tag: 'Semantic Catalog'
    },
    {
      name: 'SQLGenerator',
      path: 'src/datapilot/domain/interfaces/sql_generator.py',
      description: 'Synthesizes dialect-specific SQL from user intents, domain rules, and schema graphs.',
      methods: [
        'generate(question, schema, context, dialect) -> str',
      ],
      tag: 'NL-to-SQL'
    },
    {
      name: 'SQLValidator',
      path: 'src/datapilot/domain/interfaces/sql_validator.py',
      description: 'Enforces strict read-only guarantees, AST safety parsing, and injection defenses.',
      methods: [
        'validate(sql, dialect, enforce_read_only) -> SQLValidationResult',
      ],
      tag: 'Security Perimeter'
    }
  ];

  const endpoints = [
    { method: 'GET', path: '/health', desc: 'Liveness probe returning process status and version', response: '{"status": "ok", "app": "Data Pilot", "version": "0.1.0"}' },
    { method: 'GET', path: '/health/ready', desc: 'Readiness probe with runtime diagnostics and provider configuration check', response: '{"status": "healthy", "environment": "development", "components": {...}}' },
    { method: 'GET', path: '/info', desc: 'Architecture metadata, supported dialects (PostgreSQL, Snowflake...), and capabilities', response: '{"app": "Data Pilot", "architecture": {"db_agnostic": true, "llm_agnostic": true}}' },
    { method: 'GET', path: '/docs', desc: 'Interactive Swagger UI OpenAPI documentation', response: 'HTML Interactive Explorer' },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-indigo-500/30">
      {/* Top Header */}
      <header className="border-b border-slate-800/80 bg-slate-900/50 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-tr from-indigo-600 via-sky-500 to-emerald-400 p-0.5 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <div className="w-full h-full bg-slate-950 rounded-[7px] flex items-center justify-center">
                <Database className="w-5 h-5 text-sky-400" />
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-white tracking-tight">Data Pilot</h1>
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  v0.1.0 Core Engine
                </span>
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                  Open Source
                </span>
              </div>
              <p className="text-xs text-slate-400">AI Data Intelligence & Natural-Language-to-SQL Platform</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <a
              href="https://github.com/niranjan2020/data-pilot"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition"
            >
              <Code2 className="w-4 h-4 text-slate-400" />
              <span>GitHub Repo</span>
            </a>
            <div className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-950/40 text-emerald-300 border border-emerald-800/40">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>15/15 Tests Passing</span>
            </div>
          </div>
        </div>
      </header>

      {/* Hero Banner */}
      <section className="border-b border-slate-800/60 bg-gradient-to-b from-slate-900/40 to-transparent py-10 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          <div className="max-w-3xl">
            <h2 className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
              Deterministic, Database-Agnostic <br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-sky-400 via-indigo-400 to-emerald-400">
                Natural-Language-to-SQL Core
              </span>
            </h2>
            <p className="mt-3 text-slate-300 text-sm sm:text-base leading-relaxed">
              Data Pilot is being built from the ground up as an open-source, self-hostable intelligence platform.
              Business rules, entity catalogs, and safety constraints are modeled as explicit Python structures—never lost in unstructured prompts.
            </p>
          </div>

          {/* Quick status counters */}
          <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="flex items-center gap-2 text-slate-400 text-xs mb-1">
                <Boxes className="w-4 h-4 text-sky-400" />
                <span>Architecture</span>
              </div>
              <div className="text-lg font-bold text-white">Modular Monolith</div>
              <div className="text-xs text-slate-400 mt-0.5">Clean Hexagonal Boundaries</div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="flex items-center gap-2 text-slate-400 text-xs mb-1">
                <Database className="w-4 h-4 text-emerald-400" />
                <span>Target Databases</span>
              </div>
              <div className="text-lg font-bold text-white">PostgreSQL Ready</div>
              <div className="text-xs text-slate-400 mt-0.5">+ Snowflake, MySQL, BigQuery</div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="flex items-center gap-2 text-slate-400 text-xs mb-1">
                <Cpu className="w-4 h-4 text-indigo-400" />
                <span>AI Providers</span>
              </div>
              <div className="text-lg font-bold text-white">LLM Agnostic</div>
              <div className="text-xs text-slate-400 mt-0.5">Gemini, OpenAI, Anthropic, Local</div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
              <div className="flex items-center gap-2 text-slate-400 text-xs mb-1">
                <ShieldCheck className="w-4 h-4 text-amber-400" />
                <span>Security</span>
              </div>
              <div className="text-lg font-bold text-white">AST Validated</div>
              <div className="text-xs text-slate-400 mt-0.5">Strict Read-Only Enforcement</div>
            </div>
          </div>
        </div>
      </section>

      {/* Tab Navigation */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-6">
        <div className="flex border-b border-slate-800 space-x-6">
          <button
            onClick={() => setActiveTab('architecture')}
            className={`pb-3 text-sm font-medium transition border-b-2 flex items-center gap-2 ${
              activeTab === 'architecture'
                ? 'border-sky-400 text-sky-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Layers className="w-4 h-4" />
            <span>Architecture & Pipeline</span>
          </button>

          <button
            onClick={() => setActiveTab('interfaces')}
            className={`pb-3 text-sm font-medium transition border-b-2 flex items-center gap-2 ${
              activeTab === 'interfaces'
                ? 'border-sky-400 text-sky-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Code2 className="w-4 h-4" />
            <span>Domain Protocols (5)</span>
          </button>

          <button
            onClick={() => setActiveTab('endpoints')}
            className={`pb-3 text-sm font-medium transition border-b-2 flex items-center gap-2 ${
              activeTab === 'endpoints'
                ? 'border-sky-400 text-sky-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Server className="w-4 h-4" />
            <span>FastAPI Endpoints</span>
          </button>

          <button
            onClick={() => setActiveTab('quickstart')}
            className={`pb-3 text-sm font-medium transition border-b-2 flex items-center gap-2 ${
              activeTab === 'quickstart'
                ? 'border-sky-400 text-sky-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Terminal className="w-4 h-4" />
            <span>Local Development</span>
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Tab 1: Architecture Pipeline */}
        {activeTab === 'architecture' && (
          <div className="space-y-8">
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6">
              <h3 className="text-base font-semibold text-white flex items-center gap-2 mb-4">
                <Activity className="w-5 h-5 text-sky-400" />
                <span>The Data Pilot Execution Pipeline</span>
              </h3>
              
              <div className="grid grid-cols-1 md:grid-cols-7 gap-2 items-center">
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-lg text-center">
                  <div className="text-xs font-mono text-sky-400 font-semibold mb-1">STEP 1</div>
                  <div className="text-xs font-medium text-white">Natural Language Question</div>
                  <div className="text-[10px] text-slate-500 mt-1">"How many on-order vessels does MSC have?"</div>
                </div>

                <div className="hidden md:flex justify-center text-slate-600">
                  <ArrowRight className="w-4 h-4" />
                </div>

                <div className="p-3 bg-slate-950 border border-slate-800 rounded-lg text-center">
                  <div className="text-xs font-mono text-indigo-400 font-semibold mb-1">STEP 2</div>
                  <div className="text-xs font-medium text-white">Semantic & Intent Discovery</div>
                  <div className="text-[10px] text-slate-500 mt-1">Resolves entities, synonyms & metrics</div>
                </div>

                <div className="hidden md:flex justify-center text-slate-600">
                  <ArrowRight className="w-4 h-4" />
                </div>

                <div className="p-3 bg-slate-950 border border-slate-800 rounded-lg text-center">
                  <div className="text-xs font-mono text-amber-400 font-semibold mb-1">STEP 3</div>
                  <div className="text-xs font-medium text-white">Template or SQL Gen</div>
                  <div className="text-[10px] text-slate-500 mt-1">Dialect-specific SQL synthesis</div>
                </div>

                <div className="hidden md:flex justify-center text-slate-600">
                  <ArrowRight className="w-4 h-4" />
                </div>

                <div className="p-3 bg-slate-950 border border-slate-800 rounded-lg text-center">
                  <div className="text-xs font-mono text-emerald-400 font-semibold mb-1">STEP 4</div>
                  <div className="text-xs font-medium text-white">AST Validation & Exec</div>
                  <div className="text-[10px] text-slate-500 mt-1">Read-only check & explanation</div>
                </div>
              </div>
            </div>

            {/* Core Layer Principles */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5">
                <div className="w-8 h-8 rounded-lg bg-sky-500/10 text-sky-400 flex items-center justify-center mb-3">
                  <Database className="w-4 h-4" />
                </div>
                <h4 className="text-sm font-semibold text-white mb-2">1. Database-Agnostic</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  PostgreSQL is our primary implementation, but all query generation and schema reflection routes through the <code>DatabaseProvider</code> protocol. Zero hardcoded dialect lock-in.
                </p>
              </div>

              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center mb-3">
                  <Cpu className="w-4 h-4" />
                </div>
                <h4 className="text-sm font-semibold text-white mb-2">2. LLM-Agnostic</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Orchestrator interacts via the <code>LLMProvider</code> contract. Easily swap Google Gemini, OpenAI, Anthropic, or local open-weights models without changing application logic.
                </p>
              </div>

              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5">
                <div className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center mb-3">
                  <ShieldCheck className="w-4 h-4" />
                </div>
                <h4 className="text-sm font-semibold text-white mb-2">3. Zero-SaaS Bloat</h4>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Pure open-source core. No multi-tenant IDs, billing stubs, or user subscriptions inside the engine. A clean API contract ensures future SaaS wrappers integrate externally.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Domain Protocols */}
        {activeTab === 'interfaces' && (
          <div className="space-y-4">
            <div className="p-4 bg-slate-900/40 border border-slate-800 rounded-xl mb-4 text-xs text-slate-300">
              Data Pilot enforces <strong>Dependency Inversion</strong> using Python 3.10+ <code className="text-sky-300">typing.Protocol</code> with <code className="text-sky-300">@runtime_checkable</code>. Domain and application services depend solely on these protocols:
            </div>

            <div className="grid grid-cols-1 gap-4">
              {interfaces.map((item, idx) => (
                <div key={idx} className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-white font-mono">{item.name}</span>
                      <span className="text-xs px-2 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 font-mono">
                        {item.tag}
                      </span>
                    </div>
                    <span className="text-xs text-slate-500 font-mono">{item.path}</span>
                  </div>
                  <p className="text-xs text-slate-400 mb-3">{item.description}</p>
                  
                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800/80">
                    <div className="text-[11px] font-mono text-slate-400 space-y-1">
                      {item.methods.map((m, mIdx) => (
                        <div key={mIdx} className="flex items-start gap-2">
                          <span className="text-indigo-400">def</span>
                          <span className="text-slate-200">{m}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tab 3: Endpoints */}
        {activeTab === 'endpoints' && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-4">
              {endpoints.map((ep, idx) => (
                <div key={idx} className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="px-2.5 py-0.5 rounded text-xs font-bold font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      {ep.method}
                    </span>
                    <span className="font-mono text-sm font-semibold text-white">{ep.path}</span>
                  </div>
                  <p className="text-xs text-slate-400 mb-3">{ep.desc}</p>
                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800/80 font-mono text-xs text-emerald-300">
                    {ep.response}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tab 4: Quickstart */}
        {activeTab === 'quickstart' && (
          <div className="space-y-6">
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
                <Terminal className="w-4 h-4 text-sky-400" />
                <span>1. Local Setup & Testing</span>
              </h3>
              <p className="text-xs text-slate-400 mb-4">
                Clone the repository, create a virtual environment, install the package in editable mode, and run the pytest suite:
              </p>

              <div className="bg-slate-950 p-4 rounded-lg border border-slate-800 font-mono text-xs text-slate-200 relative group">
                <button
                  onClick={() => copyToClipboard('git clone https://github.com/niranjan2020/data-pilot.git\ncd data-pilot\npython3 -m venv .venv\nsource .venv/bin/activate\npip install -e ".[dev]"\npytest -v', 'c1')}
                  className="absolute top-3 right-3 p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 transition"
                  title="Copy commands"
                >
                  {copiedCmd === 'c1' ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                </button>
                <div className="space-y-1 text-slate-300">
                  <div className="text-slate-500"># Clone & activate environment</div>
                  <div>git clone https://github.com/niranjan2020/data-pilot.git</div>
                  <div>cd data-pilot</div>
                  <div>python3 -m venv .venv && source .venv/bin/activate</div>
                  <div className="text-slate-500 pt-2"># Install with development dependencies</div>
                  <div>pip install -e &quot;.[dev]&quot;</div>
                  <div className="text-slate-500 pt-2"># Run test suite</div>
                  <div className="text-emerald-400">pytest -v</div>
                </div>
              </div>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
                <Server className="w-4 h-4 text-emerald-400" />
                <span>2. Start the API Server</span>
              </h3>
              <p className="text-xs text-slate-400 mb-4">
                Run the server via the CLI script or uvicorn:
              </p>

              <div className="bg-slate-950 p-4 rounded-lg border border-slate-800 font-mono text-xs text-slate-200 relative group">
                <button
                  onClick={() => copyToClipboard('datapilot\n# or\nuvicorn datapilot.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload', 'c2')}
                  className="absolute top-3 right-3 p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 transition"
                  title="Copy commands"
                >
                  {copiedCmd === 'c2' ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                </button>
                <div className="space-y-1 text-slate-300">
                  <div>datapilot</div>
                  <div className="text-slate-500 pt-1"># Or with live reload via uvicorn</div>
                  <div>uvicorn datapilot.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload</div>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950 py-6 text-center text-xs text-slate-500">
        <p>Data Pilot • Open-Source AI Data Intelligence Platform • Licensed under Apache-2.0</p>
      </footer>
    </div>
  );
}
