"""Tasks from the Schematize study (Sawczyn et al., 2026; code MIT, github.com/pwr-ai/schematize).

Each of their three Polish legal research problems becomes a question-set task:
  * the research question (English), with the researcher's original Polish request
    and the clarification dialogue they released;
  * a document collection: judgments from JuDDGES/pl-court-raw (CC BY 4.0) that
    match the problem by keyword, sampled at random from one shard of the dataset;
  * the gold is their expert question sets (3 experts per problem), not a table;
    evaluation is question coverage, as in their protocol;
  * the schemas their pipeline generated with five LLMs are kept as reference
    schemas, labelled as model output, not gold.

  python3 schematize_tasks.py <schematize_repo> <selected.json> <example_schemas.json> <docs_dir> <out.jsonl>
"""
import hashlib, json, os, sys, yaml

QUESTION = {
    "pl_age": "In Polish court judgments on drug offences (possession, trafficking and production), is the defendant's age associated with the type and severity of the sentence, including suspension and conditional discontinuance?",
    "pl_medical_errors": "How do Polish civil courts set the amount of compensation for medical errors, and which circumstances affect the amounts awarded to patients?",
    "pl_personal_rights": "What kinds of personal-rights violations do people bring to Polish civil courts, and are these cases becoming more trivial over time?",
}
TITLE = {"pl_age": "Defendant age and sentencing in drug-offence judgments",
         "pl_medical_errors": "Compensation for medical errors in civil courts",
         "pl_personal_rights": "Personal-rights violation cases in civil courts"}
EXAMPLE = {"pl_age": "age", "pl_medical_errors": "medical_errors", "pl_personal_rights": "personal_rights"}

repo, selp, exp, docs, outp = sys.argv[1:6]
sel = json.load(open(selp, encoding="utf-8"))
schemas = json.load(open(exp, encoding="utf-8"))
out = []
for case in ("pl_age", "pl_medical_errors", "pl_personal_rights"):
    c = yaml.safe_load(open(os.path.join(repo, "data", "cases", case + ".yaml"), encoding="utf-8"))
    ed = os.path.join(repo, "data", "eval", case)
    experts = {f[:-5]: yaml.safe_load(open(os.path.join(ed, f), encoding="utf-8"))["questions"]
               for f in sorted(os.listdir(ed)) if f.endswith(".yaml") and not f.startswith("rejected")}
    documents = []
    for r in sel[case]:
        b = (r["full_text"] or "").encode("utf-8")
        fn = f"plcourt/{r['judgment_id']}.txt"
        open(os.path.join(docs, fn), "wb").write(b)
        documents.append({"document_id": "pl-court:" + r["judgment_id"], "title": r.get("docket_number"),
                          "kind": "txt", "url": "https://huggingface.co/datasets/JuDDGES/pl-court-raw",
                          "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b), "file": fn,
                          "licence": "CC BY 4.0 (JuDDGES/pl-court-raw)", "identity_check": "dataset record",
                          "court": r.get("court_name"), "date": (r.get("judgment_date") or "")[:10]})
    out.append({
        "task_id": "schematize:" + case, "task_type": "question_set", "source": "schematize", "stratum": "schematize",
        "domain": "law", "language": "pl",
        "question": QUESTION[case], "question_provenance": "schematize_case+rewritten",
        "question_author_text": c["user_input"],
        "clarification_dialogue": {"researcher_request": c["user_input"], "clarifying_questions": c["problem_help"],
                                   "researcher_answers": c["user_feedback"]},
        "paper": {"title": TITLE[case] + " (Schematize study)", "journal": "arXiv 2609.22209", "year": "2026",
                  "id": "schematize:" + case, "url": "https://github.com/pwr-ai/schematize",
                  "licence": "MIT (code and question sets)"},
        "expert_questions": experts,
        "reference_schemas": {m: v for m, v in schemas.get(EXAMPLE[case], {}).items()},
        "schema": None, "rows": [], "documents": documents,
        "counts": {"rows_in_published_table": 0, "rows_exported": 0, "documents": len(documents), "columns": 0,
                   "expert_questions": sum(len(v) for v in experts.values())},
        "quality": {"tier": "core", "grounding_rate": None, "suspect_rows": None, "judged": False, "verdict": None,
                    "issues": ["no gold table: evaluate by coverage of the expert questions",
                               "documents chosen by keyword from one shard of the dataset (judgments from 2008 to 2014)"]},
    })
open(outp, "w", encoding="utf-8").write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in out))
for t in out:
    print(t["task_id"], "| documents", t["counts"]["documents"], "| expert questions", t["counts"]["expert_questions"], "| reference schemas", len(t["reference_schemas"]))
