# Running ScheMatiQ on the benchmark

`src/run_schematiq_benchmark.py` runs schematiq-lib on one task and scores it. It was tested in this session up to the model calls: document preparation on a table task (23 PDF and XML documents turned into text), and conversion, column mapping and scoring on a simulated extraction. Schema discovery and value extraction need a model key and the library, and were not run here.

## Verified from the ScheMatiQ code (main, 2026-09-29)

- Schema discovery reads only `.txt`, `.md` and `.html` files (`load_documents` in `schematiq/core/schematiq.py`). The runner therefore converts PDFs with pdftotext and strips JATS XML to text first.
- Extracted rows are JSONL. Each row lists its source files in `_papers`, as the file stem, and each cell is an object with an `answer` (`value_extraction/core/table_builder.py`, `paper_processor.py`).
- The model is chosen by `backend.provider` (`gemini`, `openai`, `together` or `hf`) through `utils.build_llm`.

## Setup

```
pip install -e /path/to/ScheMatiQ/schematiq-lib
export GEMINI_API_KEY=<API_KEY>
python3 src/fetch_documents.py data/benchmark     # table tasks only: downloads into data/benchmark/documents
```

## One task

```
python3 src/run_schematiq_benchmark.py --export data/benchmark --task ccp:amendment_rules --work runs/ccp_amendment
```

Everything is written to the `--work` folder:

| File | What it holds |
|---|---|
| `docs/` | The documents as text |
| `schema.json` | The discovered schema |
| `extraction.jsonl` | The extracted rows |
| `system.csv` | The rows, one per document |
| `mapping.json` | Gold column to system column. It is checked automatically; correct it and rerun with `--from-step 6`. |
| `score.json` | Cell accuracy and the errors on the analysis questions |

Question-set tasks (`schematize:*`) stop after discovery and write `coverage.json`: the share of each expert's questions that the schema can answer, as judged by the same model.

## A first set, one task of each kind

```
for t in ccp:amendment_rules scdb:roberts retractions:plos_one PMC13534118 schematize:pl_personal_rights; do
  python3 src/run_schematiq_benchmark.py --export data/benchmark --task "$t" --work "runs/${t//:/_}"
done
```
