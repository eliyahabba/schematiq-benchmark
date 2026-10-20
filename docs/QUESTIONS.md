# Research questions in the benchmark

## The problem

Most tasks take their question from the authors' own text: a PROSPERO field, the title, or an aim sentence in the abstract. That text is faithful to the paper, but it often does not work as a question:

- **It describes the paper.** For example: "This survey reviews AI alignment through a game-theoretic lens." In an earlier export of 126 tasks, 34 questions were phrased this way.
- **It is not a question.** Only 28 of those 126 ended with a question mark.
- **It leans on context.** For example: "this survey maps the evaluation landscape around *that gap*."
- **It carries a section label or background.** For example: "Materials and methods We performed ...".

## The rule

A good research question for this benchmark:

1. is a question, or at most two linked questions;
2. names the object of study and the domain: the population, system or phenomenon;
3. says what is to be learned across the documents: an effect, a comparison, a prevalence, or a landscape of methods;
4. can be understood without the paper;
5. adds nothing the authors did not state in the title, abstract or registration;
6. does not list the gold table's columns.

## Coverage

Every accepted or core task whose question was not already a question has been rewritten: 147 tasks in total.

- The rewrites are in `data/questions_rewritten.json`. Each keeps the authors' text next to it.
- In the export, 150 of 152 questions end with a question mark at the last count (earlier: 28 of 126).
- In the round of 107 rewrites, the median grounding is 0.875.
- Gold column names appear 116 times in the rewrites, against 102 in the authors' texts. This is mostly the object of study that the question now names, which is often also a column name ("Datasets", "Benchmark", "Restenosis").
- Two rewrites that echoed a column's wording without the authors having used it were cut back: "privacy and utility" for face de-identification, and "when is each most useful" for LLM training efficiency.

## The process

- **Rewriting.** The question is rewritten from the paper's title, abstract and the authors' own aim sentence. The table is not shown to the writer. The authors' text is kept as `question_author_text`.
  - In this session Claude wrote the rewrites (`questions_rewritten.json`, 39 tasks).
  - `rewrite_prompt.txt` holds the same instructions for an LLM API, to be used at scale. It was not run in this session.
- **Automatic checks** (`question_checks.py`), stored with every rewrite:
  - **Grounding:** the share of the question's content words that occur in the title, abstract or aim text. The pilot median is 0.90. The words below 0.8 were inflections ("prevalent" versus "prevalence") and function words.
  - **Column names spelled out, before and after rewriting:** in the pilot, 45 before and 39 after. The rewrites that name more columns do so through topic words that are also column names (for example "restenosis" and "Restenosis"). One rewrite that adopted the abstract's wording of a column was changed.
- **Judging.** A judge then checks the result, as for every task.
