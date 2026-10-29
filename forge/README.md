# Offline twin forge

Run from the repository root with its existing .venv. Nothing here is imported
by the interview app. Live authoring is explicit; the default mode is replay.

## 100-question pilot

Use a PowerShell session with BASETEN_API_KEY and MODEL_API_KEY already exported.
The forge never reads an environment file. This command asks for the CSV's path;
it does not copy the CSV or print question/solution text.

```powershell
$env:LLM_BACKEND = "open_weights"
$csvPath = Read-Host "Full path to the bank CSV"
.\.venv\Scripts\python.exe -m forge.run --mode live --csv $csvPath --limit 100 --per-topic "probability=30,expected value=30,combinations and permutations=25,statistics=15" --topics "probability,expected value,combinations and permutations,statistics" --budget-usd 40 --work-dir data/forge/pilot20b
```

Re-run the same command to resume. Completed accepted, rejected and nonnumeric
items are skipped. --topics sets priority, not an exclusive topic filter.
--limit counts eligible questions after the loader's exclusions.
Run with --mode replay for keyless operation using matching recorded calls.

Live mode checks for both exported keys before opening the bank or reserving spend.

No live pilot was run during implementation. The committed funnel.json starts
as not_run. Acceptance rate, cost per accepted template and the builder's 30-item
audit must be assessed after a real pilot; synthetic tests are not pilot evidence.

## Files and privacy

- CSV input retains question_id, title, difficulty, topics, statement and solution.
  Common id/question/worked_solution/tags aliases are supported. Locked, empty,
  image-bearing rows and whitespace-normalized duplicate statement hashes drop.
- data/forge/state.json holds private checkpoints and the spend ledger.
- data/forge/calls/ uses the existing llm.replay.CallStore format and exact
  backend/request hashes for every original/repair call.
- data/forge/mapping.json is the only accepted-template/source-ID mapping.
  Source IDs also occur in the private per-item checkpoint, never in public JSON.
- content/forge/forge_<hash>.json contains accepted, precomputed instance data.
  It includes no source statement, solution quote, generated solver or simulator.
  Templates wait with review_status=pending_builder_review.
- forge/funnel.json contains counts, numbers, model/cost configuration and gate
  results only. Topic counters are multi-label and need not sum to the overall count.

The default private directory is already git-ignored. --work-dir may select a
subdirectory of data/forge for another job. CSVs, prompts, source mappings and
generated code must never be added to git. No existing recordings/captures are used.

## Models and calls

The author is llm.backends.open_weights, Muse Spark Open
(meta-models/muse-spark-open-1026) on Baseten, selected with LLM_BACKEND=open_weights.
The answer extractor, alternative-reading checker and blind twin checker use
llm.backends.meta_api, muse-spark-1.3. Calls use low effort, strict JSON schemas,
a 4,000-token cap, and reject truncation/refusal. Open weights additionally gets
the schema in the prompt and at most one repair for invalid JSON/schema output.
There is no automatic cross-host fallback.

The simulator is authored in a separate, stateless request. Its user payload has
only question and part2_question text, with named placeholders. It never receives
the stored answer, worked solution, solver code, wrong solvers or solution steps.
Blind-check requests have only one rendered question.

## Code gates

1. The stored final answer must be quoted verbatim from the worked solution.
   Integer/fraction/percent/scientific numeric strings become Fraction values;
   unsupported symbolic or compound expressions fail. Decimal answers use a stated
   tolerance with a verbatim quote, or half the last decimal unit when unstated.
2. The solver at original parameters must match the stored value (within its
   stated decimal tolerance). Named steps must match the returned intermediate values.
3. The acceptance gate requires at least **20 distinct precomputed instances**.
   Candidate selection starts with original values, each parameter's low/high
   edge and joint edges, then uses distance across normalized parameter ranges
   to spread the remaining values. A bounded reserve supplies replacements.
4. Every exported instance lists all 2-4 named wrong-method values. Candidates
   with a wrong value equal to the correct answer, or within its stated tolerance,
   are dropped; fewer than 20 survivors rejects the template. Valid edge-ish
   values are prioritised. Each instance also includes exact Fraction strings:
   `separation.by_misconception` lists `misconception`, `absolute_gap` and
   `relative_gap` (absolute gap divided by absolute correct answer; `null` for
   a zero correct answer). `separation.min_wrong_pair_gap` is the smallest
   absolute gap among every pair of wrong values; zero is allowed. The runtime
   can select the most informative instances without executing generated code.
5. The child runs at least --trials random samples per point (default 20,000).
   It computes the exact sample mean and variance itself, then SE; the solver
   must be within four SE. The simulator cannot supply its own SE/trial count.
   Every sample must draw events. No imported solver, no reseeding a sample.
   At least one checked point must have nonzero sample variance; dummy random
   calls followed by a deterministic exact-answer formula are rejected.
6. Up to three alternative readings are independently answered. If any answer's
   interval overlaps the stored answer interval, reject unless it matches the
   stored answer and all three twin answers match the main solver exactly.
   Equivalent readings are recorded; non-numeric alternatives fail closed.
7. Spark 1.3 must solve one new rendered twin exactly, blind to reference code/key.
8. Novelty is the maximum of token-sequence similarity and word-trigram
   containment against every loaded eligible statement, considering both the
   template and its original rendering. At/above --max-similarity rejects.
   The engineering default is 0.70, configurable before starting a job; it is
   not a measured guarantee of originality. Duplicate generated templates do
   not inflate acceptance counts.

Part 2 adds exactly one parameter to the same setup. Its own solver, random
simulator, named wrong methods, edges, novelty and blind answer must pass.
A failed part 2 is omitted while a verified base template may still be accepted.
Accepted part 2 is attached to at least 20 base instances and carries the same
wrong-value and separation fields. Its extra parameter is spread across its full
range. Only precomputed data is exported; generated code never runs at app runtime.

## Subprocess boundary

Generated code is run only by this worktree's Python in an isolated -I -S -B child,
in a temporary working directory with credentials removed from its environment.
The child uses AST capability checks, minimal builtins, module facades exposing
only permitted math/fractions/random/itertools/functools operations, and an audit
hook denying file, socket, subprocess and native-library capabilities.
Attributes beginning with underscore, introspection/dynamic execution, classes,
decorators and global/nonlocal declarations are rejected. Each sample gets fresh
generated globals; parameters are read-only and shared facades cannot be mutated.

Windows Job Objects enforce process memory and CPU limits; POSIX uses rlimits.
The parent enforces wall time and kills a stalled child. Default limits are
128 MB and 10 seconds per invocation, configurable with --memory-mb/--timeout-s.
Resource setup fails closed. These are defenses for generated Python, not an
invitation to use the child as a general-purpose shell or container.

Solvers define solve(params) -> {"answer": Fraction/int, "steps": {name: Fraction/int}}.
Wrong methods define solve(params) -> Fraction/int.
Simulators define sample(params, rng) -> one sampled numeric outcome whose
expectation equals the requested answer. The harness repeats sample; code must
not return a precomputed aggregate or an exact answer disguised as an experiment.

## Budget, cost and recovery

The $40 cap is cumulative per private job, including previous invocations.
A conservative upper reservation for UTF-8 input/framing and the API-capped
output is saved before each live request. Completed calls are charged from
usage.prompt_tokens and usage.completion_tokens. Missing usage/failed calls
retain the conservative reservation and are flagged usage_unknown_calls.

Prices are configurable USD per million tokens:

```text
--price meta_api=INPUT,OUTPUT --price open_weights=INPUT,OUTPUT
```

Defaults are explicit budgeting assumptions of $1.25 input / $4.25 output per
million for each backend, not a statement of current Baseten billing.
Set actual agreed rates before the first call; the cap and reported costs are
evaluated at configured rates. Prices and verification settings, including the
20-instance gate and format,
are frozen for resumption. Older verification revisions are refused; start a
separate job with --work-dir data/forge/pilot20b if one already exists. Limit, topic
order and budget up to $40 can change.

Every cached exact response is reused, including repairs and failures. A job
lock prevents concurrent ledger writers. If a crash leaves a charged/reserved
request without a saved response, status becomes unresolved_call: automatic
resubmission is refused. Reconcile that private ledger entry with the call store
and provider billing before manually deciding whether a retry is appropriate.

Exit 0 means the selected items finished processing, including rejections.
Exit 2 means budget_stop, replay_missing, interrupted or unresolved_call.
Exit 1 means a configuration/input/lock error. Exception bodies and bank text are
not printed. Funnel latency is recorded model-call latency counted once, not the
wall time of a replay invocation.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_forge_data.py tests/test_forge_sandbox.py tests/test_forge_models.py tests/test_forge_pipeline.py tests/test_forge_instances.py tests/test_forge_cli.py --tb=short
```

All fixtures are invented. Gate, budget, privacy, resume and CLI tests use fake
models; sandbox tests also execute small invented programs under actual process
limits. No live API calls or bank/capture reads are needed.

## Pilot 20b changes

Use a fresh private directory for this revision; older verification settings are
refused. After exporting both keys and configuring agreed prices, run:

```powershell
$env:LLM_BACKEND = "open_weights"
$csvPath = Read-Host "Full path to the bank CSV"
.\.venv\Scripts\python.exe -m forge.run --mode live --csv $csvPath --limit 100 --per-topic "probability=30,expected value=30,combinations and permutations=25,statistics=15" --topics "probability,expected value,combinations and permutations,statistics" --budget-usd 40 --work-dir data/forge/pilot20b
```

Each question occupies one quota only. Matching reallocates multi-topic questions
when necessary to fill scarce topics. Quotas must sum to --limit; --topics orders
ties. No other topic silently fills a shortfall. The funnel reports requested,
selected and missing counts. Selection and verification revision are frozen per job.

Topic labels are parsed as whole JSON/Python list entries or delimited labels,
case/whitespace cleaned, and common singular/plural aliases are combined. Single
characters, malformed prose/notes and non-label values are excluded. The cleaned
vocabulary contains only labels occurring in at least five CSV rows, before the
locked/image/empty/duplicate row filters. Infrequent labels are dropped; questions
can remain untagged. The funnel publishes this vocabulary with row counts.

Numeric parsing accepts LaTeX frac/dfrac/tfrac, rational strings, approximation or
equals prefixes, decimal percents, scientific notation and trailing units/words.
It refuses multiple answers and arithmetic expressions. Unparsed answers are
reported as counts, never echoed in logs. Decimal answers without a stated
tolerance use half a unit in the last stated decimal place (percent precision is
divided by 100); verification records tolerance_source=implied. Integer/fraction
answers stay exact. An explicitly stated decimal tolerance still needs its quote.

Solvers/steps return int or Fraction only. Float returns are TypeError failures;
samplers accept bool/int/float/Fraction, with bool converted to int. Step labels
are normalized to snake_case in declarations and returned values; collisions or
unusable names still fail.

One gate repair per item is allowed for TypeError, invalid template fields or
step names, forbidden imports, or timeout. The author receives the draft, gate
and safe error class. A simulator repair is a separate stateless call receiving
only the question text and safe gate/error labels, never any solver, solution,
answer, previous simulator code or earlier messages. Both calls use the existing
budgeted record/replay. Pending repairs resume without duplicate spend. Schema
format repair remains independently bounded to one correction per model call.
No repair bypasses any acceptance gate. The funnel counts accepted_after_repair.

An alternative reading matching the stored answer within its recorded tolerance gets
three distinct twin questions, without reference answers or solver code. Only
three exact matches to the main solver establish an "equivalent reading"; any
mismatch rejects. Four SE, twenty instances, blind twins, novelty, random-event
checks and sandbox/isolation restrictions remain unchanged. Render is counted
passed only after successful rendering/validation. Accepted content still waits
for builder audit and must not be committed before that review.
