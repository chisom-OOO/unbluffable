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

## Scale run: content quality revision

Run from this worktree with both API keys already exported. This selects 500
source questions in the requested split and reserves at most $20 at the configured
token prices. It is resumable in its own fresh private directory:

```powershell
$env:LLM_BACKEND = "open_weights"
$csvPath = Read-Host "Full path to the bank CSV"
.\.venv\Scripts\python.exe -m forge.run --mode live --csv $csvPath --limit 500 --per-topic "probability=150,expected value=120,combinations and permutations=100,statistics=80,games=50" --topics "probability,expected value,combinations and permutations,statistics,games" --budget-usd 20 --work-dir data/forge/scale1
```

Content-quality changes:

- Every exported instance carries interview_friendly, interview_friendly_score
  and interview_friendly_basis. The exact ANSWER form determines the score:
  integer=3; reduced fraction with denominator at most 100=2; exactly terminating
  decimal/percent with at most two significant figures=1; otherwise 0. A rounded
  approximation never qualifies. This is an answer-arithmetic heuristic, not a
  measured difficulty rating of the whole question.
- At least 20 instances and at least 10 friendly instances are required.
  Sampling continues into the bounded, well-spread reserve when needed; all
  retained points still pass the existing exact/Monte Carlo/wrong-method gates.
  Optional part 2 must separately retain 20 points and 10 friendly points.
- wrong entries have unique exact values and a misconceptions LIST, even for
  singletons. All source method names survive a merge. Separation still has one
  row per method; min_wrong_pair_gap keeps its original solver-method meaning
  (zero when methods collide with each other). min_distinct_wrong_pair_gap is
  the minimum among distinct exported wrong values, or null for a single value.
  A collision with the CORRECT answer still drops the instance.
- Each instance, including part 2, has spoken_text. Code expands exact numeric
  literals, fractions, decimals, scientific notation, percents and common
  comparison/arithmetic symbols into spoken English, without rounding.
- The author must write natural interview English and state assumptions such as
  fair coins/dice, independence and replacement. Dollar signs, backslash
  commands, redundant 1 * coefficients and count phrases such as "5 squared
  observations" trigger the existing single author-repair round. Persistent
  bad wording rejects the entire template, including bad optional part-2 text.
  These checks supplement the builder's wording audit.
- After numerical/blind/novelty checks, one short Spark 1.3 checker call chooses
  topic from the actual cleaned vocabulary using only generated question text.
  The old primary bank label is source_topic; topics retains the source labels.
  A missing vocabulary or an out-of-vocabulary result cannot be accepted.
  This call uses the same private record/replay and cost ledger.

Verification revision 4 / instance format 3 prevents an old finished checkpoint
from skipping the new content gates. No generated content is committed before
builder review. Four SE, simulator isolation, the blind twin and novelty gates
are unchanged.

## Verified family forge

The family importer is a separate command in forge.family_run, implemented by
forge.families. It retains all 75 variants per family from the supplied verified
CSV; it does not reword questions, invent ranges or drop difficult instances.

From the voice worktree, with BASETEN_API_KEY already exported:

```powershell
$env:LLM_BACKEND = "open_weights"
.\.venv\Scripts\python.exe -m forge.family_run --mode live --csv "C:\Users\chiso\unbluffable\data\bank\quant_interview_7575.csv" --budget-usd 5 --work-dir data/forge/families1
```

Only Spark Open is called. MODEL_API_KEY is not needed for this workflow.
Default mode is replay; matching recorded jobs replay without either key.
Prices use the same configurable --price flags and durable usage/reservation
ledger. The family budget defaults to and is capped at $5.

The loader requires exactly 75 distinct variants per family and a passing source
verification result. PASS_EXACT values have zero tolerance, including exact
decimal literals; PASS_NUMERICAL uses the positive verification_tolerance from
the CSV. Answers/tolerances are exported as canonical exact Fraction strings.
Parameters, question text, topic and difficulty retain their CSV meanings;
subtopic becomes source_topic. Source row IDs stay in ignored private mappings.

For each family, two deterministic representative variants (question, parameters,
solution, reasoning_focus) go to the author. It writes one solver, 2-4 named
wrong-method solvers and named steps. All 75 values must match before solver
verification passes. Every wrong method is checked on every variant. A wrong
value equal to the answer or inside its recorded tolerance fails that family's
misconception gate. Equal wrong values merge with all misconception names, and
the existing separation metrics are exported.

One complete draft repair is allowed after a code-gate failure, through the
existing record/replay and budget ledger. Both calls are recorded. Schema-format
repair remains bounded by the shared Models implementation. There is no live
retry of a failed/uncertain billed request.

A persistent failure still exports all 75 trusted CSV answers, with wrong=[] and
verification.misconceptions_verified=false. Correct steps are retained only if a
solver already passed all 75 checks; otherwise steps=[]. Verification records
which checks passed and the safe failure class, never pretending the fallback
passed a generated-code check. Finished successes/failures never spend again.
A budget stop, missing replay or unresolved call exports CSV-only pending
families too; these stay resumable and are not marked finished.

Batched sandbox calls compile once per solver and run every variant with fresh
generated globals, under the same capability, memory, CPU and wall-time limits.
Structured parameters expose immutable tuples/mappings, preserve nonnumeric
string labels, and convert numeric strings to exact Fractions. Existing sandbox defaults remain unchanged.
No generated code is included in public artifacts or executed at app runtime.

Every instance includes interview_friendly and spoken_text from the shared
helpers. All 75 instances are retained regardless of their friendliness score.
Imported wording is preserved exactly in text, including existing coefficients;
spoken conversion does not apply the twin-author wording rejection to this CSV.

Template follow_up is the lowest-numbered variant's question/reference pair.
Every instance also carries its own follow_up, preserving families whose
follow-ups vary across variants. The report marks that variation.

Outputs:
- content/forge/family_<family_id>.json: precomputed data, pending builder review.
- data/forge/families1/: source fingerprint, private code/call records, progress
  and source-row mapping, plus the durable funnel.json.
- forge/funnel.json: the latest family summary, also printed as aggregate JSON.

The funnel separates exported families, verified misconceptions, terminal
fallbacks, pending families, repairs, stages, per-topic totals, usage, cost and
recorded latency. Run the same command to resume. Exit 0 means every family was
processed (including honest fallbacks); exit 2 means pending work remains after
a budget/replay/interruption stop. Source/configuration errors exit 1.
Generated content remains uncommitted for the builder's audit.

### Recheck cached families after parameter conversion fixes

Structured sandbox parameters now recursively turn numeric strings (fractions,
decimals, integers and scientific notation) into exact Fractions. Nonnumeric
labels remain strings; native JSON integers remain ints. Lists, including nested
lists, become immutable tuples; nested objects remain read-only mappings.

Each authoring example carries its verified answer, and a percentage is a fraction
of one (26% is 13/50). A solver that returns percent points fails the gate as
percent_points_not_fraction rather than verified_value_mismatch, so the repair is
told the fix; it is never accepted.

Use --retry-families with comma/space-separated fallback family IDs in the SAME
work directory and --mode live to author them again under the current prompt. Their
old drafts move to retry_history; only those IDs are touched, and each is retried
once per prompt revision. --budget-usd is the work directory's running total, so
set it to the amount already spent plus the new allowance.

Use --recheck-families with comma/space-separated family IDs in the SAME work
directory and --mode replay. It rechecks only those IDs, using the cached corrected
draft and then the cached original draft if needed. It never makes a new model
call, clears no ledger entries and does not grant another repair round. The
existing all-75, exact/tolerance, step and wrong-collision gates still apply.

Rechecks are checkpointed by parameter-runtime revision. A resumed command skips
already completed rechecks and does not touch other families' checkpoint entries
or exports. The funnel reports the selected IDs, verified/fallback counts and
additional calls/cost. Name errors or invalid misconception names that persist
in both cached drafts remain explicit fallbacks.

The same runtime revision also fixes permitted plain imports whose Python fromlist
is None; the module/member allowlist and network restrictions remain unchanged.

## Coding specs (decision log 26)

`python -m forge.coding_specs` asks Muse Spark Open, once per software family, for a Python
signature (typed parameters mapped to the instance params, return type) and a short
statement. Code verifies each spec on every variant: parameter types, the forge's own
verified solver called through the signature (it must reproduce every stored answer), and
each wrong method (kept only when wrong on some test; its outputs per test are stored).
One repair per family. Only verified specs are written, to `content/coding/`, with the
solver and wrong-method source. Calls are recorded under the work directory; replay
needs no key.

```
python -m forge.coding_specs --family-state ../unbluffable-voice/data/forge/sw2/state.json \
    --work-dir data/forge/coding1 --mode live --budget-usd 1
```
