# Semantic Entity and Value Resolution

Data Pilot now has a deterministic semantic-resolution stage between schema/catalog loading and SQL generation.

## What it resolves

A semantic catalog can define entities and their attributes:

- entity: customer
- synonyms: customers, client
- display column: customer_name
- attribute: country -> country
- attribute: segment -> segment

Questions can then resolve into a provider-independent QueryIntent:

    show customers in India
        -> entity = customer
        -> filter = country = "India"

    show customers where segment is enterprise
        -> entity = customer
        -> filter = segment = "enterprise"

    show orders for customer Acme
        -> entity = order
        -> filter = customer_name = "Acme"

## Safety properties

The resolver:

1. does not call an LLM;
2. does not query database values;
3. does not generate SQL;
4. preserves ambiguity instead of silently selecting an entity;
5. keeps explicit API parameters higher priority than inferred values;
6. passes the structured intent to the SQL generator as context.

Template parameters can be populated from resolved filters when their names match the semantic attribute or canonical column.

## Why this boundary matters

Entity/value resolution is deliberately separate from SQL generation. This allows Data Pilot to support deterministic rules, optional future LLM-based intent extraction, different SQL-generation strategies, and multiple database providers.

The next related capability is controlled query/resource policy enforcement, followed by a generic local database fixture and evaluation harness.