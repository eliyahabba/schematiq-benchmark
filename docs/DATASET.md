# The ScheMatiQ benchmark: what a task is and how it gets in

## A task

A task is one published review, turned into four parts:

| Part | What it is |
|---|---|
| **Question** | The research question the review answers. It is phrased as a question and can be understood without the paper. |
| **Documents** | The studies the review includes. Each one was downloaded and checked to be the right paper: its DOI is printed in the file, or its title appears in it. |
| **Schema** | The columns of the review's study table. |
| **Gold table** | One row per document: what the review's authors extracted from that study. Only rows whose document is in hand are kept. |

A system gets the question and the documents, and must produce the schema and the table.

## Three kinds of task

| Kind | Rows are | Gold | How a system is scored |
|---|---|---|---|
| **Table** | Studies included in a review (tens of rows) | The review's study table | Schema and cells against the table |
| **Database** | Units of analysis, such as court cases or retracted papers (hundreds of rows) | A coded research database | Schema, cells, and the answers to the research question computed from the database |
| **Question set** | No gold rows | Expert questions the data must be able to answer | Coverage of the expert questions |

Cells in a database can be codes, numbers or free text (for example the notes of Retraction Watch). What separates it from a table is that it is meant to be queried and aggregated, not read row by row.

## Where tasks come from

- **Europe PMC systematic reviews** (biomedicine and health):
  - the table is read from the article's JATS XML, or from a Word or Excel supplement when that is more complete;
  - tables of the same studies are joined.
- **Campbell and BMC Systematic Reviews** (social science, health services).
- **Environmental Evidence systematic maps**: their coded map databases, with studies linked by title.
- **arXiv surveys and systematic reviews** (computer science, EE, statistics, physics): LaTeX tables in which each row cites one paper.
- **Tasks added by hand**, through `import_manual.py`.
- **U.S. Supreme Court Database** (law, database): one task per Chief Justice era, each with 200 cases. The documents are the opinions, from the Caselaw Access Project.
- **Retraction Watch database** (meta-research, database): one task per journal group, each with up to 200 retractions. The documents are the retraction notices, from PMC.
- **Schematize study** (law, question set): three Polish legal research problems with expert question sets. The documents are judgments from JuDDGES/pl-court-raw.

## Where the question comes from

The question is taken from the first of these that exists:

1. the review question registered in PROSPERO;
2. a title phrased as a question;
3. the aim stated in the abstract, or the paper's own research questions.

When that text describes the paper instead of asking a question ("This survey reviews ..."), it is rewritten from the title and abstract, without looking at the table. The authors' text is kept alongside. Rules: `QUESTIONS.md`.

## Rules for inclusion (tier "core")

A task is core when all of these hold:

- the question is usable;
- the table has one row per study;
- the table passes the automatic gates, which reject appraisal tables, bibliographic lists and taxonomies;
- at least 5 documents are downloaded and verified;
- a judge accepted the question and the table.

The judge is currently Claude (an LLM). A human spot-check is still pending.

If the table covers only part of the question, the task is "extended".

## Quality measures stored with each task

| Measure | What it records |
|---|---|
| Grounding | The share of short cells (numbers, or up to four words) found word for word in their own document |
| Judge verdict and notes | The judge's decision and the reasons for it |
| Question provenance | Where the question came from, and the rewrite checks: grounding in the title and abstract, and gold column names spelled out |
| Document licence | Documents obtained through a publisher's TDM route are marked "do not redistribute" |

## Scoring a database task

`src/evaluate_database.py <task.json> <system.csv> [mapping.json]` compares a system's database with the gold. Rows are matched by `document_id`. Columns are matched by a mapping file, or by name.

- **Cells:** for each mapped column, the share of rows that agree with the gold. Text is compared after normalising, numbers within 1%, and ';' lists by set overlap.
- **Answers:** every database task carries `analysis_questions` with gold answers: the share of each category, the share of documents mentioning each common value of a multi-valued column, and the mean of numeric columns. The same questions are answered from the system's database, and the scores are the mean absolute error of the shares and the relative error of the means.

Tested on a copy of a gold database with 10% of cells corrupted. It gave a cell accuracy of 0.90, a share error of 0.04 and a mean error of 0.01.

Question-set tasks are scored by coverage of the expert questions. Schematize's evaluator (MIT) can be used for that; it is not run here.
