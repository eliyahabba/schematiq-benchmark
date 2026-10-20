# Using the Elsevier route

From this sandbox, the key authenticates, but full-text requests return 403 "Requestor configuration settings insufficient", and ScienceDirect search returns 401. Elsevier grants text-mining access by the institution's entitlement. There are two ways to get it:

1. **Run from the university network.** Elsevier recognises the campus IP range.
   ```
   export ELSEVIER_API_KEY=<API_KEY>
   export ELSEVIER_TRY=1
   python3 src/fetch_docs.py data/build/tasks.jsonl downloads 3000 --retry
   ```
2. **Run from anywhere with an institutional token.** The library, or Elsevier's integration support, can issue an institutional token (`insttoken`) for the key. The route then sends it as `X-ELS-Insttoken`.
   ```
   export ELSEVIER_INSTTOKEN=<INSTTOKEN>
   ```
   Then run the same command as in option 1.

Keep requests slow (the route waits 1 second between calls). Documents obtained this way are tagged as subscription content and must not be redistributed.
