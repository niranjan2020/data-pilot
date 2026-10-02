# Local development infrastructure

Data Pilot uses PostgreSQL as the authoritative relational/catalog store. Qdrant is an auxiliary vector store for semantic retrieval and is not required for basic SQL correctness.

With Rancher Desktop configured for the Moby/Docker engine:

```powershell
cd infra
docker compose up -d
docker compose ps
```

PostgreSQL:
- host: localhost
- host port: 5433\n- container port: 5432
- database: datapilot
- user: datapilot
- password: datapilot_local

Qdrant:
- REST: http://localhost:6333
- gRPC: localhost:6334

To load the generic evaluation fixture after PostgreSQL is healthy:

```powershell
Get-Content ..\tests\fixtures\postgresql\schema.sql | docker exec -i datapilot-postgres psql -U datapilot -d datapilot
Get-Content ..\tests\fixtures\postgresql\seed.sql | docker exec -i datapilot-postgres psql -U datapilot -d datapilot
```

These credentials are development-only. Production credentials must come from secrets/configuration.


## Local roles

- `datapilot-adventureworks` (separate container): customer/source database on `localhost:5432`.
- `datapilot-postgres`: Data Pilot platform/catalog database on `localhost:5433`.
- `datapilot-qdrant`: semantic vector store on `localhost:6333` (REST) and `6334` (gRPC).

For the backend to persist discovered metadata, set:

```env
METADATA_DATABASE_URL=postgresql://datapilot:datapilot_local@localhost:5433/datapilot
```

Qdrant is intentionally started now but is not yet populated. PostgreSQL remains the source of truth for semantic configuration.
