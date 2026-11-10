# Model card: payee type classifier

**What it does.** Labels each of the 61,798 payee names in the payments data (7syw-q4cy, as grouped in `ref.map_payee_vendor`) with one of five types, and measures whether a text model labels them better than the name rules the dashboard already uses. Code: `src/models/payee_classifier.py`. Input: `sql/mart/60_v_payee_class_input.sql`. Outputs: `mart.d_payee_class` (one row per payee name) and `mart.d_payee_class_eval` (the evaluation). Settings: `config/assumptions.yaml` (`payee_classifier`). Checks: `src/pipeline/checks_ml.py`.

**It produces better data, never savings.** A label says who a payment went to; nothing here is a finding about the payment.

## Classes

| Class | Meaning |
|---|---|
| business | for-profit companies, banks, utilities, health-care service companies, professional practices |
| government | public bodies: counties, cities, towns, boards of education, public schools, State and federal agencies, public authorities and commissions, public universities and community colleges that say so in the name |
| nonprofit | foundations, associations, churches and congregations, charities, community organizations, volunteer fire and rescue companies |
| individual/withheld | a person's name (including a person paid in care of an agency, or an estate of a named person), or a withheld name |
| other | an organization whose type the name does not settle: hospitals, health systems and medical centers, universities and colleges that do not say they are public |

## Baseline: the rules

`reference/payee_type_rules.csv` applied by `mart.vendor_type` (unchanged), mapped to the classes by `payee_classifier.rule_to_class`: Government -> government, Non-profit -> nonprofit, Business or other / Financial institution / Utility -> business, Health care organization / Education institution -> other. "Business or other" is the rules' default for every name no rule matched (`type_basis = 'default'`, 53,281 of 56,590 vendors); mapping it to business is the charitable reading, and the one the dashboard uses.

## Evaluation set

400 names drawn by `payee_classifier.draw_sample` (seed 20261110): stratified by all-years spend bucket (<$100K, $100K-$1M, $1M-$10M, $10M-$100M, $100M+) and rule label, one name per cell per pass so small cells are fully represented. Because every rule label gets equal weight, the sample over-represents the small rule classes (Utility, Financial institution) and has only 65 default-labeled names; metrics are for this stratified sample, not population estimates.

**Labeling criteria** (applied to the name text alone, in this order):

1. **individual/withheld**: a person's name in either order (`GINA MCNEIL`, `WILSON CAROL ESTHER`), a person in care of an agency (`... /BALTIMORE CITY-DHCD`), an estate of a named person, a person with a bank as escrow agent.
2. **government**: COUNTY / CITY OF / TOWN OF / BOARD OF EDUCATION / PUBLIC SCHOOLS / COMMISSIONERS / HEALTH DEPT / POLICE DEPARTMENT / named State or federal agency / public AUTHORITY or COMMISSION / COMMUNITY COLLEGE / STATE UNIVERSITY / UNIVERSITY OF <state> (and their units). A company whose name contains a public word is not government (`GOVERNMENT SALES LLC`, `FEDERAL DEVELOPMENT LTD. PART.`, `CECIL COUNTY PEDIATRICS`, `PFG/CARROLL COUNTY FOODS`).
3. **nonprofit**: FOUNDATION, ASSOCIATION/ASSN, SOCIETY, CHURCH/CONGREGATION/PARISH/saint's-name parish, ARC OF, BOYS & GIRLS CLUB, GOODWILL, FOOD BANK, CENTER FOR, COMMUNITY ORGANIZATION/NETWORK/DEVELOPMENT CORP, VOLUNTEER FIRE/RESCUE, HEADSTART, LEGAL AID, orchestras, social-service names (`NEIGHBORHOOD SERVICE CENTER INC`, `JUDE HOUSE INC`), mission-statement names (`CHANGE THE CONVERSATION INC`).
4. **other**: HOSPITAL, HEALTH SYSTEM, MEDICAL CENTER (without LLC/PC/PA), and UNIVERSITY/COLLEGE not public by name (`JOHNS HOPKINS UNIVERSITY`, `CECIL COLLEGE`). A university foundation is nonprofit; a university practice plan with PA is business.
5. **business**: LLC, LP, LLLP, LLP, PC, PA, CO, CORP, LTD, COMPANY, BANK, utility names, a commercial trade word (TRUCKING, CONSTRUCTION, PHARMACY, SALES, ENTERPRISES, HOME HEALTHCARE SERVICES, CHILD CARE CENTER INC), a known commercial brand (`WALGREENS`, `BRITISH AIRWAYS`). A hospital that is an LLC is business.
6. **unsure**: the name does not settle the type: INC with no trade or mission cue (`CREATIVE OPTIONS INC`, `GAUDENZIA INC`), a bare place or brand name (`SHEPPARD PRATT`, `NATIONAL AQUARIUM BALTIMORE`), an acronym. Excluded from the metrics and counted.

**Single annotator.** The labels in `reference/payee_labels_sample.csv` (`my_label`) were made by one annotator (Claude, Nov 10, 2026) from the name text, without the grants data or the rule label's evidence. They are to be re-reviewed by Sierra: fill `her_label` where she disagrees; the build then uses `her_label` instead and the metrics change on the next `make build`. Names labeled individual/withheld are written as `[individual: name withheld, see payee_key]`; look a name up locally with `SELECT payee FROM mart.v_payee_class_input WHERE payee_key = '...'`.

Result: 400 labeled; **36 unsure (excluded)**; 364 scored: business 182, other 70, nonprofit 56, government 48, individual/withheld 8. 96 labels differ from the rule class (noted in the file).

## Model

TF-IDF character n-grams (`char_wb`, 2-5, min_df 2, up to 200,000 features, sublinear tf) + multinomial logistic regression (C = 4, class_weight balanced, random_state 20261110), trained on the rule classes of 61,294 payee names: every name except the 400 evaluated **and every other name of the same vendors** (504 held out), so a spelling variant of an evaluation name is never in training. It learns only the classes the rules produce, so it **cannot predict individual/withheld**. **Combined** = the rule's label where a name rule or the grants data decided, the model's label where the rules fell to the default. A default-labeled name goes to the review queue when the model is confident (probability >= 0.6, set before evaluation) it is another type, or when the model's confidence is below 0.6; a rule-decided name goes there when the model disagrees with the rule.

## Results (Nov 9, 2026 extract, run 20261109T154457Z; 364 scored names)

| | Rules | Model | Combined |
|---|---|---|---|
| Accuracy | **0.714** | 0.668 | **0.714** |
| Macro F1 (5 classes) | **0.560** | 0.468 | **0.560** |
| Accuracy on the 52 scored default-labeled names | 0.808 | 0.808 | 0.808 |
| Share of dollars classified (all-years payments, positive) | 64.1% | 98.8% | 98.9% |
| Share of dollars whose label changes vs the rules | 0 | 5.9% | 2.6% |

Per class F1 (rules / model / combined): business 0.780 / 0.754 / 0.780; government 0.648 / 0.648 / 0.648; nonprofit 0.688 / 0.250 / 0.688; other 0.684 / 0.687 / 0.684; individual/withheld 0 / 0 / 0 (neither can produce it). Business: rules precision 0.894, recall 0.692 (missed business is mostly labeled "other" by the Health care and Education rules, e.g. `HOSPITAL FURNITURE RESTORATION`, `UNIVERSITY FOR TOTS ... CHILDCARE`, `COLLEGE PARKWAY LLLP`). Government precision 0.583: the Government rule's words also hit companies and nonprofits (`GOVERNMENT SALES LLC`, `ARC OF HOWARD COUNTY INC`, `URBANA VOLUNTEER FIRE DEPARTMENT INC`).

"Share of dollars classified" is the share of all-years payments whose label rests on evidence rather than the default: for the rules, a name rule or the grants data; for the model, a probability of at least 0.6. **The model's 98.8% overstates it**: most of those dollars are confident "business" labels learned from the rules' own default bucket, so they repeat the default rather than add evidence. The honest measure of what the model adds is the 2.6% of dollars the combined method relabels, and on the sample those changes did not move any score.

**Decision: not promoted.** Combined does not beat the rules on macro F1 (0.560 = 0.560: on the 65 default-labeled names in the sample the model said business every time except two names, both labeled unsure), so `final_label` = the rule label. The model stays as a **review queue** (2,475 names): 1,181 + 308 + 288 default-labeled names the model would call nonprofit, government or other, including real misses of the rules, e.g. `BD OF EDUCATION OF PG CO` (the rules miss the abbreviation; $1.04B all years), `MARYLAND STATE POLICE`, `CHARLES CO BOARD OF EDUC`, `ASSOCIATED CATHOLIC CHARITIES INC`, and confident "other" for health plans (`CAREFIRST BLUECHOICE INC`, `AETNA HEALTH INC`). A review of that queue, or a rule added for what it finds, is how the labels improve; the model is not a substitute for the review.

## Limits

* Single-annotator, name-only labels; the 400 are a stratified sample, so per-class numbers have wide intervals (individual/withheld has 8 names).
* Training labels are the rules' labels: the model can at best generalize the rules (abbreviations, misspellings), and inherits their errors. A model trained on reviewed labels is the next step once Sierra's review exists.
* Names that may be a person's are never published: `d_payee_class.payee` shows "Payee not named (may be an individual)" for business-labeled names with no organization word (`payment_screen.org_name_pattern`) and for every name labeled individual/withheld; `payee_key` (md5 of the name) links back to the database.
