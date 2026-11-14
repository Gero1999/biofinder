# Testing and benchmarks

Install `requirements.txt`, then run from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The suite uses `unittest` and predefined API responses. No credentials, paid
model calls, or live dataset downloads are required. All test classes inherit
guards that reject DNS resolution, socket connections, and UDP sends. The DNS
policy unit test replaces resolution with a predefined loopback response; it
never resolves a real host. Router tests inject tool mocks. No CI workflow is added.

| Suite | Coverage |
| --- | --- |
| `test_annotation.py` | Query classification, routing, search fallbacks, authorization, retries, cancellation, deadlines, budgets |
| `test_unit.py` | TTL/LRU, exact calculation caching, provider response parsing, malformed responses, model-context approval, private DNS rejection, quotation validation, invalid calculations and criteria |
| `test_integration.py` | CLI output, scoped cache reuse/freshness, access revocation, cancellation/resume snapshots, deferred calculation planning, local dotenv precedence, searchable/empty PDFs |
| `test_scenarios.py` | All six investigations through actual clients, router, document lookup, ingestion, calculation, and report validation with mocked transport |
| `test_performance.py` | Thirty warm-cache runs with equivalent findings and fewer requests; exact 100,000-row counting |

Run a single suite with, for example:

```bash
python3 -m unittest discover -s tests -p 'test_integration.py' -v
```

## Scenario fixtures

`tests/fixtures/scenario_1.json` through `scenario_6.json` contain synthetic case
documents, complete CSV inputs, and predefined model/search/source responses.
They contain no real study or patient data. `fixtures.FixtureTransport` returns
provider-shaped response envelopes, so client parsing and orchestration remain
real code paths. Table answers are calculated from fixture rows, not supplied
as canned results.

All prose, CSV rows, and test PDFs in these fixtures are generated for this
repository. Public-source URLs use the reserved example domains, and browser
responses are generated locally; no website is scraped or republished. The
access-denied case is a simulated error, not an attempt to open a restricted
dataset. Credentials and signed-link strings in rejection tests are obvious
dummy values, not usable credentials. The `pypdf` dependency is installed
normally rather than vendored into the repository. This describes the offline
tests only; a future live deployment needs its own review of data permissions
and provider/site terms.

1. Donor inflation: 120 library rows represent 18 distinct donors, failing a
   30-donor requirement.
2. RNA-seq compatibility: two of six feature identifiers are unmatched against
   the supplied reference.
3. Longitudinal eligibility: two baseline-window rows, two post-treatment rows,
   one outside-window row, and one unknown time.
4. Access/reuse: blocked primary source, public alternative, and unresolved
   commercial permission; the answer stays partial.
5. Multi-omics pairing: three exact one-to-one pairs; an ambiguous key is
   excluded from verified pairs, failing the required minimum.
6. Microbiome confounding: phenotype is perfectly confounded with platform and
   missing controls remain unresolved; the answer stays partial.

These golden responses verify execution and constraints. They do not evaluate a
live model's planning quality, adversarial robustness, scientific judgment, or
paraphrase entailment. Accepted statements must equal literal evidence quotes.

## Performance and request cost

```bash
python3 -m benchmarks.run --runs 30 --output /tmp/biofinder-benchmark.json
```

Each repetition creates a fresh cache for a cold run, then repeats the same case
with that cache for a warm run. The runner tests all six scenarios, checks that
claims/calculations/criteria/status stay identical, forbids network connections,
and reports median/p95 local elapsed time and request counts. Request counters
include mocked model, search, and source retrieval operations.

An example Python 3.12 run in the development workspace (30 cold and 30 warm
runs per scenario) measured cold p95 between 0.95 and 1.77 ms and warm p95 between
0.72 and 1.09 ms. Five scenarios reduced mocked HTTP requests from four to two;
scenario 4 reduced five to three because the access-denied source is retried on
a new investigation. Both model calls remain in each warm run. Findings were
unchanged. These timings vary with hardware and load.

The tests use generous local regression ceilings: warm p95 below one second and
the complete 100,000-row count below five seconds. They do **not** establish the
live latency, token cost, concurrency, large-document retrieval targets, or
availability goals in the requirements. Fixture token counts are invented;
there is no actual API expenditure or valid dollar estimate. Live provider
validation is a separate, explicitly configured activity.

## Local configuration

Only `.env.example` is checked in. The configuration test uses a temporary file
with synthetic values, verifies injected variables win, and checks that shell
expressions remain plain text. Do not add local `.env` files or real credentials
to fixtures, test output, benchmark reports, or commits.
