# SYNTHETIC evaluation — Kreng-jai Bridge

**No volunteer or real workplace data was used.** All D1/D2/D4 personas, styles and feedback and the D3 histories are SYNTHETIC.

## Measured privacy and utility

80 test messages, 160 training messages, 20 candidate authors. Lower attacker accuracy means less measured leakage.

| Metric (SYNTHETIC D1) | Before | After | Chance / majority baseline |
|---|---:|---:|---:|
| Stylometric author accuracy | 100.00% | 3.75% | 5.0% |
| LLM author accuracy | 100.00% | 7.50% | 5.0% |
| Gender accuracy | 93.75% | 46.25% | 50.0% |
| Seniority accuracy | 95.00% | 20.00% | 25.0% |
| Texts containing gender/seniority markers | 95.00% | 0.00% | 0% target (no chance model) |

| Utility / operational metric (SYNTHETIC D1) | Measured |
|---|---:|
| Mean meaning score (1–5) | 3.825 |
| Meaning score ≥ 4 | 57.5% |
| Pipeline ok rate | 93.8% (75/80) |
| Blocked: attacker / validation or model error | 4 / 1 |
| Mean internal attacker rounds | 1.137 |
| Fresh pipeline latency p50 / p95 | 4.28 / 5.67 s |

For the 75 released texts only: stylometric author accuracy 4.0%, LLM author accuracy 8.0%, gender accuracy 45.3%, seniority accuracy 21.3%; meaning mean 4.013, with 61.3% scoring ≥ 4.

Measured interpretation: author attribution drops substantially after rewriting, but the independent LLM attacker still identifies 6/80 authors (7.5%, versus 5% chance). This pilot does not establish anonymity. Meaning preservation is incomplete: 34/80 outputs score below 4, including the 5 empty blocked outputs.

## Theme evaluation (SYNTHETIC D4)

| Metric on AFTER text | Measured |
|---|---:|
| Six-cluster adjusted Rand index | 0.0028 |
| Six-cluster purity | 23.8% |
| assign_theme slug accuracy | 90.0% |
| Native threshold clustering: cluster count | 66 |
| Native threshold clustering: ARI / purity | 0.0566 / 100.0% |

On the 75 released texts only: six-cluster ARI 0.6646, purity 77.3%, assign_theme accuracy 92.0%. Native threshold clustering produces 61 clusters, with ARI 0.0637 and purity 100.0%.

The all-output fixed-k result includes empty blocked texts. Empty vectors can consume separate clusters and force unrelated nonempty texts into one group; the released-only result measures the content actually available downstream. High purity from many near-singleton native clusters is fragmentation rather than recovery of the six themes. Fixed-k grouping is substantially better on released text, but still imperfect; native threshold clustering fragments the data.

## Friction detection (SYNTHETIC D3)

| Metric | Mean ± sample SD across seeds 1–5 |
|---|---:|
| Recall | 100.0% ± 0.0% |
| Precision | 100.0% ± 0.0% |
| Median detection delay (minutes) | 0.000 ± 0.000 |

| Seed | Truth episodes | Recall | Precision | Median delay (min) |
|---|---:|---:|---:|---:|
| 1 | 17 | 100.0% | 100.0% | 0.000 |
| 2 | 17 | 100.0% | 100.0% | 0.000 |
| 3 | 17 | 100.0% | 100.0% | 0.000 |
| 4 | 17 | 100.0% | 100.0% | 0.000 |
| 5 | 17 | 100.0% | 100.0% | 0.000 |

The retained six-hour replay on seed 1 gives a median delay of 240.0 minutes, showing the scheduler artifact. A zero median at 15-minute resolution does not mean every episode is detected instantly; these medians combine timer-based and event-driven episodes.

## Method and reproducibility

- D1 contains 240 LLM-generated Thai messages: 20 personas × 12 messages, two per each of six architecture seed themes. There are 10 female and 10 male cards, and five cards per seniority level. D2 is the gender/seniority fields; D4 is the theme field in d1.jsonl. All are synthetic labels, not self-reported attributes.
- The deterministic split holds out one message from four rotating themes per persona (8 train / 4 test). All six themes occur in that persona's training set. Test text is disjoint from train; personas are intentionally shared for closed-set author attribution. split.json records the exact split. The pipeline roster contains all 20 MemberProfiles with three training samples each.
- Classical attackers fit TF-IDF character 2–5 grams + LogisticRegression(max_iter=2000, random_state=42) on training originals only, then predict on raw test text and run_pipeline.final_text. Author chance is 5%; gender majority is 50%; seniority majority is 25%. A single percent step on 80 tests is 1.25 percentage points.
- The separate forced-choice LLM attacker receives all 20 style cards and two training samples per card. It sees neither test labels nor the original when attacking AFTER, and must pick an author even without evidence. This differs from the internal pipeline attacker, which may abstain and only blocks correct guesses above its confidence threshold.
- A separate LLM call judges each original/final pair on an anchored 1–5 concern/impact/request scale. Blocked outputs remain empty and are included in every metric; release status and individual judgments are saved. Accuracy is closed-set top-1; marker leakage uses the production leak_markers function.
- The first ten held-out texts from ten distinct personas are timed in serial with LLM response cache reads disabled. Every response is still saved. p50/p95 use numpy percentiles on those ten end-to-end durations; dated first-run measurements are reused on cached reruns. This ordered subset contains the first ten (female) personas, so timing is not a balanced demographic sample; endpoint load and small n also affect these numbers.
- cluster_offline has no k parameter. The evaluation temporarily substitutes its AgglomerativeClustering constructor in process to set n_clusters=6 and distance_threshold=None, leaving its production Thai tokenizer, TF-IDF, cosine distances and average linkage intact. Native threshold-based results are also reported; no production clustering source is edited. assign_theme is called separately on final text, not read from the pipeline's joint structure/classify output.
- D3 replays generate_history(seed) every 15 minutes, with deterministic context_check filtering. Episodes match unique (kind, affected_hash, ref), and delay is first detection minus injected detectable_at, clipped to zero. Metrics measure rules plus deterministic context filtering, not the LLM judge, outreach delivery, rate limits or human usefulness. tick_minutes=360 retains six-hour replay.
- Run `uv run python eval/run_all.py`; optional `--only gen|privacy|theme|engine` resumes a stage. All LLM calls go through app.llm.chat/chat_json with a global semaphore of four, error retries and SHA-256 request caches under eval/cache. Pipeline snapshots include production source hashes and roster inputs. No API keys are written to cache. Cached data is synthetic and is an explicit offline-evaluation exception to the live product's no-original-persistence rule.

## Honest limitations

This is a synthetic pilot, not evidence of anonymity for real Thai teams. Explicit persona style signatures make raw attribution easier and may exaggerate the apparent privacy gain. The same qwen3.5 model family generates data, rewrites, attacks and judges meaning; correlated behavior and self-grading bias can overstate protection and utility. Synthetic theme slugs and concerns closely follow the classifier's seed list, making semantic classification easier than unseen workplace issues. No human meaning ratings, external attacker model, adaptive attacker trained on rewritten text, unseen-persona test, or sensitive-context linkage attack is included.

The held-out sample is small and contains repeated messages from each persona. Point estimates are not statistically independent per-message evidence; no significance claim or generalization guarantee is made. Accuracy near chance and zero dictionary marker leaks do not prove an attacker cannot identify authors, gender or seniority. The marker detector covers its predefined dictionary only. Blocking can suppress both identity and meaning, so the ok rate must be read alongside attacker and meaning results.

D3 seeds vary background metadata but retain the same injected episode templates and schedules, so low or zero cross-seed SD is expected and does not demonstrate real-world robustness. Episode matching does not penalize repeat alerts, and clipped detection delay can hide an alert before the ground-truth boundary. The six-hour replay is available for comparison but the headline uses 15 minutes. Future evaluation needs consented real data, independent attacks and human utility judgments.
