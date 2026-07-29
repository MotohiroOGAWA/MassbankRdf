# MassBank RDF

MassBank RDF is a GUI application for searching MassBank MS/MS spectra and connecting the results to the PubChem, HMDB, and KNApSAcK knowledge graphs (KGs). It helps users explore related compounds, pathways, diseases, biospecimens, organisms, and biological activities.

The GUI consists of Gradio applications mounted on a FastAPI server. The main processing flow is:

```text
Input spectrum
    ↓
Search the local MassBank SQLite database by spectral similarity
    ↓
Generate SPARQL queries from the InChIKeys in the search results
    ↓
Search PubChem / HMDB / KNApSAcK
    ↓
Build a KG evidence JSON document
    ↓ (optional)
Interpret compound origin and biological plausibility with Azure OpenAI
```

## GUI features

### Knowledge Graph Search

This workflow searches MassBank using one peak list and then queries the configured KGs using the InChIKeys of the highest-ranked candidates.

- Paste an m/z and intensity peak list
- Search MassBank by cosine similarity
- Configure ion mode, precursor m/z, tolerances, and other search conditions
- Limit the number of unique MassBank InChIKeys used for KG lookup
- Connect to the KGs using either full or short InChIKeys
- Inspect the generated SPARQL queries
- View and download the KG evidence JSON
- Optionally interpret the evidence with Azure OpenAI

When `Connect KG using short InChIKey` is enabled, KG records are matched using the first 14 characters of each InChIKey (the connectivity layer). This includes candidates with the same connectivity but different stereochemical or protonation layers. Full InChIKeys returned by the KGs are preserved in the output.

The result page contains the following tabs:

- `MassBank`: similar spectra and compound metadata
- `SPARQL`: queries generated for each KG
- `KG`: integrated KG evidence JSON
- `Interpretation`: per-compound LLM interpretations and a cross-compound summary

### Common Peak Annotation

This workflow extracts product-ion peaks shared by multiple spectra and uses them to search and annotate MassBank candidates.

- Enter multiple peak lists separated by blank lines
- Extract common peaks within the selected m/z tolerance
- Rank peaks by the number of records in which they occur
- Search MassBank using the highest-ranked common peaks
- Annotate common m/z values with MassBank hits
- Run KG lookup and optional LLM interpretation

The workflows provide a `Load Example` button for quickly checking the expected input format and basic behavior.

### MSP Knowledge Graph Annotation

This workflow accepts multiple `.msp` files, reads all valid
spectra, and searches MassBank separately for every spectrum. It selects up to
the configured number of candidate InChIKeys per spectrum, de-duplicates them
across the complete MSP file, and enriches them with PubChem, HMDB, and
KNApSAcK evidence in chunks. `Ion_mode` and `PrecursorMZ` are automatically
taken from each MSP record when available. The GUI reports progress separately
for the MassBank and KG stages.

Multiple MSP files can be uploaded together. Assign a sample class such as
`PR` or `WT` to every file before running. An output archive name is required;
the run is rejected when it is blank. Because the GUI runs on a server, it
cannot directly write to an arbitrary client path such as `D:\...`. The
complete result is packaged as a ZIP in the Output tab; use the browser save
dialog to store it on the client PC. The browser MassBank table is
aggregated by MassBank record and reports how many spectra and files were
assigned to each record. Detailed spectrum-level results remain available in
the local output:

```text
massbank_candidates_by_spectrum.csv
spectrum_inchikey_annotations.csv
massbank_record_summary.csv
class_inchikey_kg_analysis.csv
kg_evidence.json
sparql/*.sparql
summary.json
```

`class_inchikey_kg_analysis.csv` reports class and other-class prevalence,
enrichment ratio, Fisher exact p-value when SciPy is available, and the KG
entity summary for each InChIKey. During MassBank processing, `checkpoint.pkl`
is updated every 25 spectra. Enable `Resume from checkpoint` with the same
files, classes, settings, and output directory to continue an interrupted run.

## Quick start with Docker

### Prerequisites

- Docker Engine
- Docker Compose v2 (the `docker compose` command)
- Network access from the container to the configured SPARQL endpoints
- A populated MassBank database at `mnt/app/data/db/massbank.sqlite3`

The `data/` directory is not tracked by Git. In a new environment, provide a populated MassBank database before starting the GUI. The normal GUI workflow requires `massbank.sqlite3`. The separate `kg.sqlite3` database is used for offline analysis and bulk KG builds; it is not required to start the GUI when online SPARQL lookup is used.

### 1. Build the Docker image

Run the following commands from the repository root:

```bash
cd /workspaces/MassbankRdf
./env/build.sh
```

The script builds `massbank-rdf-app-env:latest` and writes the host UID, GID, and port settings to `env/.env`.

### 2. Start the GUI container

```bash
./env/create_gui_container.sh
```

Open the following URL in a browser:

```text
http://localhost:7865
```

The GUI container runs in development auto-reload mode by default. Changes
under `mnt/app/massbank_rdf/` restart the Uvicorn/Gradio process automatically.
The browser may need a refresh after the restart. To disable auto-reload:

```bash
GUI_RELOAD=0 ./env/create_gui_container.sh
```

To use a different port, set `GUI_PORT` when starting the container:

```bash
GUI_PORT=7860 ./env/create_gui_container.sh
```

### 3. View the logs

```bash
docker compose \
  --env-file env/.env \
  -f container/docker-compose.yml \
  logs -f massbank-rdf-gui
```

### 4. Stop and remove the GUI container

```bash
SERVICE_NAME=massbank-rdf-gui ./env/rm_container.sh
```

## Running directly in a Python environment

If the dependencies from the Docker image are already installed, start the application directly from the application directory:

```bash
cd /workspaces/MassbankRdf/mnt/app
python -m massbank_rdf.gui.server --host 0.0.0.0 --port 7860
```

Then open `http://localhost:7860`.

The main dependencies are defined in `env/Dockerfile` and `env/requirements.txt`. The application uses Python 3.11, Gradio 5, FastAPI/Uvicorn, SQLAlchemy, SPARQLWrapper, RDKit, and the OpenAI SDK. Docker is recommended for a reproducible environment.

## GUI routes

| URL | Description |
| --- | --- |
| `/` | Workflow selection page |
| `/kg/input/` | Knowledge Graph Search input page |
| `/kg/result/` | Knowledge Graph Search result page |
| `/common-peak/input/` | Common Peak Annotation input page |
| `/common-peak/result/` | Common Peak Annotation result page |
| `/msp-kg/input/` | MSP Knowledge Graph Annotation input page |
| `/msp-kg/result/` | MSP Knowledge Graph Annotation result page |

`/kg/` and `/common-peak/` redirect to their respective input pages.

## KG endpoint configuration

SPARQL endpoints are configured in:

```text
mnt/app/massbank_rdf/gui/settings/endpoints.json
```

The configuration contains entries for `massbank`, `pubchem`, `hmdb`, and `knapsack`. The KG lookup workflow primarily uses PubChem, HMDB, and KNApSAcK.

```json
{
  "hmdb": {
    "name": "HMDB",
    "endpoint": "http://your-host:3030/HMDB/query",
    "graph": {
      "enabled": false,
      "iri": ""
    },
    "auth": {
      "user": "",
      "password": ""
    }
  }
}
```

- `endpoint`: SPARQL endpoint URL
- `graph.enabled`: whether the configured named graph should be used
- `graph.iri`: named graph IRI
- `auth.user` / `auth.password`: Basic authentication credentials

The default HMDB and KNApSAcK URLs target a private network. If the application runs outside that network, replace them with endpoints available from the container. Do not commit an `endpoints.json` file containing credentials to a public repository.

Restart the GUI container after changing the configuration:

```bash
./env/create_gui_container.sh
```

## LLM interpretation with Azure OpenAI

LLM interpretation is optional. Enable `Run LLM interpretation after KG lookup` on the input page and provide:

- Azure OpenAI endpoint
- Deployment name
- API version (default: `2024-10-21`)
- API key
- Output language
- Sample origin / context

For Knowledge Graph Search, the LLM uses the KG evidence to produce:

- Interpretations of biological roles, diseases, pathways, and biospecimens
- Origin candidates: `endogenous`, `dietary`, `drug`, or `exogenous_other`
- Provenance indicating whether a claim is grounded in the KG, model knowledge, or both
- Biological plausibility relative to the supplied sample context
- Likely biological false-positive candidates
- A summary across all interpreted compounds

GUI values, including the API key, are held temporarily in server memory for the associated browser session. The default session lifetime is one hour. Use appropriate access controls when deploying the application in a shared environment.

## Data and output

```text
mnt/app/data/db/massbank.sqlite3   MassBank search database (required by the GUI)
mnt/app/data/db/kg.sqlite3         Normalized KG database (offline use)
```

KG evidence and LLM interpretation results can be downloaded as JSON from the result page. GUI session data is stored in memory and is lost when the server restarts.

### Building short-InChIKey databases

The following command extracts short InChIKeys from the MassBank database, queries PubChem, HMDB, and KNApSAcK with short-InChIKey SPARQL, and then builds both a normalized KG database and its 1NF representation:

```bash
cd /workspaces/MassbankRdf/mnt/app
python data/db/build_short_inchikey_databases.py
```

The default outputs are:

```text
data/db/kg_short_inchikey.sqlite3
data/db/kg_short_inchikey_1nf.sqlite3
```

This process does not convert the existing `kg.sqlite3`. It performs fresh SPARQL lookups using the 14-character connectivity block. In the resulting databases, `kg_inchikeys.inchikey` contains the queried short InChIKey, while metadata returned for all matching full InChIKeys is linked to that short key.

Both outputs also contain `inchikey_short_inchikeys`, with one row per original full InChIKey:

| Column | Description |
| --- | --- |
| `inchikey` | Original 27-character full InChIKey |
| `short_inchikey` | Corresponding 14-character short InChIKey |

Custom input and output paths can be supplied as follows:

```bash
python data/db/build_short_inchikey_databases.py \
  --massbank-db-path data/db/massbank.sqlite3 \
  --short-db data/db/kg_short_inchikey.sqlite3 \
  --short-1nf-db data/db/kg_short_inchikey_1nf.sqlite3
```

## Repository structure

```text
MassbankRdf/
├── container/
│   └── docker-compose.yml       GUI and development container definitions
├── env/
│   ├── Dockerfile               Python runtime environment
│   ├── requirements.txt
│   ├── build.sh                 Build the Docker image
│   └── create_gui_container.sh  Start the GUI
└── mnt/app/
    ├── massbank_rdf/
    │   ├── db/                  MassBank and KG SQLite access
    │   ├── gui/                 FastAPI / Gradio GUI
    │   ├── models/              Data models
    │   └── services/
    │       ├── kg/              SPARQL generation and KG lookup
    │       ├── llm_interpretation/
    │       └── common_peak_annotation/
    ├── demo/                    MSP input and LLM interpretation demos
    ├── tests/                   unittest test suite
    └── data/                    Local databases and analysis output (not tracked)
```

## Tests

The test suite currently uses both `test*.py` and `Test*.py` naming conventions. Run both discovery commands:

```bash
cd /workspaces/MassbankRdf/mnt/app
python -m unittest discover -s tests -p 'test*.py'
python -m unittest discover -s tests -p 'Test*.py'
```

## Troubleshooting

### `no such table: massbank_peak_records`

The file at `mnt/app/data/db/massbank.sqlite3` is missing, empty, or has not been populated. Place a built database containing the required tables at that path. An empty SQLite file may be created automatically, but it cannot be used for searching.

### KG lookup times out

- Check the endpoint URLs in `endpoints.json`
- Confirm that the endpoints are reachable from the container
- Check VPN or private-network connectivity
- Reduce the number of InChIKeys per search with `Max MassBank InChIKey for KG`

### The GUI opens, but the KG result is empty

- Confirm that the MassBank results contain valid InChIKeys
- Inspect the generated queries and status messages in the SPARQL tab
- Try short InChIKey matching if full InChIKey matching returns no records
- Test the PubChem, HMDB, and KNApSAcK endpoints individually

### LLM interpretation does not run

- Confirm that the LLM checkbox is enabled
- Confirm that the endpoint, deployment, and API key are all present
- Confirm that the deployment supports Structured Outputs
- Inspect `failures` and error messages in the Interpretation tab
