# The benchmark

`tasks.jsonl` has one task per line. The fields shared by every kind of task:

| Field | What it holds |
|---|---|
| `task_id` | Task identifier |
| `task_type` | `table` when missing, `database`, or `question_set` |
| `domain` | Research domain |
| `question` | The research question given to a system |
| `question_author_text` | The authors' original wording, when the question was rewritten |
| `documents` | The documents, each with a URL, SHA-256 hash and licence |
| `quality` | Tier, judge verdict and known issues |

Fields that depend on the kind of task:

| Field | Kind | What it holds |
|---|---|---|
| `schema` | table, database | The gold columns |
| `rows` | table, database | One per document: `document_id` and `cells` |
| `analysis_questions` | database | Questions with gold answers computed from the gold database |
| `expert_questions` | question set | The gold of the task |
| `reference_schemas` | question set | Schemas produced by models; not gold |

Other contents of this folder:

- `tables/`: each gold table as CSV.
- `documents_text/`: the texts of documents that come from open collections (court opinions, constitutions, retraction notices, Polish judgments).
- The PDFs and XML files of table tasks are not stored. `python3 src/fetch_documents.py data/benchmark` downloads them into `documents/` and checks each hash.
- `blocked_oa.csv`: open-access documents that the download scripts could not fetch.
