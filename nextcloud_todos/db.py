from sqlalchemy import MetaData
from sqlalchemy.orm import declarative_base

# No schema in metadata: on Postgres the role's search_path is `nextcloud_todos`
# (set by the Vault static role); on SQLite (tests) schema qualification is a no-op.
metadata = MetaData()
Base = declarative_base(metadata=metadata)
