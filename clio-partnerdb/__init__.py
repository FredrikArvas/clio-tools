"""
clio-partnerdb — Shared identity register for the Clio ecosystem.

All Clio modules that deal with persons or organizations (clio-agent-obit,
clio-crm, clio-forening, …) consume this package. It owns the schema,
migrations, and core CRUD helpers.

Design principles (ADD-002):
  - Stable UUID4 per partner — never changes, even as attributes evolve
  - Mutable facts stored as claim rows with provenance
  - Life events (birth, death, marriage, …) stored as event rows with time + place
  - Full audit log for every mutation (transaction time)
  - Module-specific context tables (watch, customer_rank, …) live here
    for convenience but may be extracted to separate DBs later

Schema versioning: PRAGMA user_version in partnerdb.sqlite.
"""

__version__ = "0.1.0"
