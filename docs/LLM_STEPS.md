# The two steps that need a model

Everything else in the pipeline is rule-based. Two steps need a model:

- **Judging** whether a task is worthy (`src/judge_tasks.py`).
- **Rewriting** a question into a research question (`src/rewrite_questions.py`).

Until now Claude did both inside chat sessions. These scripts do the same with Gemini, through `src/gemini_client.py`. They write into the same files (`data/build/judgments.json` and `data/build/questions_rewritten.json`), so `finalize.py` and `export_benchmark.py` work unchanged.

Set `GEMINI_API_KEY` (see the README). The model defaults to `gemini-3.8-flash`; change it with `--model` or `GEMINI_MODEL`.

## Calibrate before use

A Gemini judge will not judge exactly as the session judge did. Measure its agreement on tasks that already have a verdict first:

```
python3 src/judge_tasks.py data/build/tasks.jsonl data/build/judgments.json --calibrate 60 --out runs/judge_calibration.json
```

The report gives:

- accept/reject agreement and Cohen's kappa;
- exact agreement on the four verdicts;
- the confusion between existing and Gemini verdicts;
- the list of disagreements, to read by hand.

Use the judge on new tasks only if the agreement is good enough for you.

## Then, for new tasks

```
python3 src/judge_tasks.py data/build/tasks.jsonl data/build/judgments.json
python3 src/rewrite_questions.py data/build/tasks.jsonl data/build/questions_rewritten.json data/build/judgments.json
python3 src/finalize.py <tasks.jsonl> <docs_manifest.jsonl> data/build/judgments.json <out.jsonl>
```

A rewrite is kept only if it passes the same checks as the session rewrites. It must end with "?", have a grounding of at least 0.6 in the title, abstract and aim, and spell out at most 2 more gold columns than the authors' text.
