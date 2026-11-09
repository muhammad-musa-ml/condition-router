| | off | scope | full |
|---|---|---|---|
| runs | 1440 | 1440 | 1440 |
| decided as labelled (bounce reason not scored) | 1080 (75.0%, seeds 52.8-88.9%) | 1179 (81.9%, seeds 61.1-97.2%) | 1187 (82.4%, seeds 66.7-97.2%) |
| wrong filing attempted | 261 (18.1%, seeds 2.8-38.9%) | 261 (18.1%, seeds 2.8-38.9%) | 261 (18.1%, seeds 2.8-38.9%) |
| wrong filing made | 261 (18.1%, seeds 2.8-38.9%) | 261 (18.1%, seeds 2.8-38.9%) | 0 (0.0%, seeds 0.0-0.0%) |
| filing made on evidence the document check refuses | 310 (21.5%, seeds 5.6-44.4%) | 310 (21.5%, seeds 5.6-44.4%) | 0 (0.0%, seeds 0.0-0.0%) |
| valid upload not filed | 70 (4.9%, seeds 0.0-19.4%) | 0 (0.0%, seeds 0.0-0.0%) | 100 (6.9%, seeds 0.0-19.4%) |
| bounced but not labelled bounce | 99 (6.9%, seeds 0.0-22.2%) | 0 (0.0%, seeds 0.0-0.0%) | 0 (0.0%, seeds 0.0-0.0%) |
| runs where a lookup or read before the first decision call was refused | 0 | 132 | 132 |
| escalated by the loop (no decision) | 0 | 0 | 0 |
| tool calls with invalid JSON | 0 | 0 | 0 |
| other-tenant uploads read | 132 | 0 | 0 |
| tool calls | 4480 | 4724 | 5034 |
| audit rows | 4480 | 4724 | 5034 |
| calls without an audit row | 0 | 0 | 0 |
| audit chains valid | True | True | True |

refusals by code: off: none; scope: ALREADY_DECIDED 136, BAD_ARGS 136, NOT_READ 122, OUT_OF_SCOPE 132; full: ALREADY_DECIDED 136, BAD_ARGS 136, EVIDENCE_NOT_IN_DOCUMENT 65, NAME_MISMATCH 3, NOT_READ 122, OUT_OF_SCOPE 132, UNREADABLE 37, WRONG_DOCUMENT_TYPE 138, WRONG_PERIOD 67
refusals in the runs where a valid upload was not filed: off: none; scope: none; full: EVIDENCE_NOT_IN_DOCUMENT 49, WRONG_DOCUMENT_TYPE 51

label -> final decision: off: bounce->bounce 354, bounce->file 153, escalate->bounce 29, escalate->escalate 186, escalate->file 57, file->bounce 70, file->file 591; scope: bounce->bounce 354, bounce->file 153, escalate->escalate 215, escalate->file 57, file->file 661; full: bounce->bounce 354, bounce->escalate 153, escalate->escalate 272, file->escalate 100, file->file 561
