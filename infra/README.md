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
- port: 5432
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
