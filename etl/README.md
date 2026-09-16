# ETL (Data Engineering)

This folder holds the data-engineering side of the platform. **Nothing is
implemented yet** - this stage only creates the structure.

The planned design is metadata-driven: pipelines are not hardcoded per source.
Configuration tables describe the sources, targets and load rules, and the
pipelines read that configuration at run time.

## Planned target platform

- Azure Data Factory (orchestration)
- Azure Data Lake Storage Gen2 (storage)
- Bronze / Silver / Gold layered architecture
- No Azure Databricks
- Transformations kept moderate

## Planned external source types

- PostgreSQL
- REST API
- FTP / SFTP

## Folders

| Folder             | Purpose                                                        |
| ------------------ | -------------------------------------------------------------- |
| `config/`          | Metadata / configuration definitions that drive the pipelines.  |
| `connectors/`      | Source-type connectors (PostgreSQL, REST API, FTP/SFTP).        |
| `pipelines/`       | Pipeline definitions and Azure Data Factory artifacts.          |
| `transformations/` | Bronze -> Silver -> Gold transformation logic.                  |
| `utils/`           | Shared helpers (logging, naming conventions, date handling).    |

## Note

The web application (frontend + backend) runs fully locally and does not
depend on Azure. Azure is used only for this ETL portion, in a later stage.
