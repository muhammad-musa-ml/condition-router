| | off | scope | full |
|---|---|---|---|
| runs | 360 | 360 | 360 |
| decided as labelled (bounce reason not scored) | 322 (89.4%, seeds 83.3-97.2%) | 330 (91.7%, seeds 83.3-100.0%) | 332 (92.2%, seeds 83.3-97.2%) |
| wrong filing attempted | 30 (8.3%, seeds 0.0-16.7%) | 30 (8.3%, seeds 0.0-16.7%) | 30 (8.3%, seeds 0.0-16.7%) |
| wrong filing made | 30 (8.3%, seeds 0.0-16.7%) | 30 (8.3%, seeds 0.0-16.7%) | 0 (0.0%, seeds 0.0-0.0%) |
| filing made on evidence the document check refuses | 37 (10.3%, seeds 2.8-19.4%) | 37 (10.3%, seeds 2.8-19.4%) | 0 (0.0%, seeds 0.0-0.0%) |
| valid upload not filed | 6 (1.7%, seeds 0.0-2.8%) | 0 (0.0%, seeds 0.0-0.0%) | 13 (3.6%, seeds 0.0-8.3%) |
| bounced but not labelled bounce | 8 (2.2%, seeds 0.0-5.6%) | 0 (0.0%, seeds 0.0-0.0%) | 0 (0.0%, seeds 0.0-0.0%) |
| runs where a lookup or read before the first decision call was refused | 0 | 17 | 17 |
| escalated by the loop (no decision) | 0 | 0 | 0 |
| tool calls with invalid JSON | 0 | 0 | 0 |
| other-tenant uploads read | 17 | 0 | 0 |
| tool calls | 1099 | 1125 | 1162 |
| audit rows | 1099 | 1125 | 1162 |
| calls without an audit row | 0 | 0 | 0 |
| audit chains valid | True | True | True |

refusals by code: off: none; scope: ALREADY_DECIDED 14, BAD_ARGS 14, NOT_READ 13, OUT_OF_SCOPE 17; full: ALREADY_DECIDED 14, BAD_ARGS 14, EVIDENCE_NOT_IN_DOCUMENT 9, NAME_MISMATCH 1, NOT_READ 13, OUT_OF_SCOPE 17, UNREADABLE 4, WRONG_DOCUMENT_TYPE 14, WRONG_PERIOD 9
runs where a valid upload was not filed, and in how many a call was refused: off: 6, 0; scope: 0, 0; full: 13, 13
refusals in the runs where a valid upload was not filed: off: none; scope: none; full: EVIDENCE_NOT_IN_DOCUMENT 7, WRONG_DOCUMENT_TYPE 6

label -> final decision: off: bounce->bounce 110, bounce->file 15, escalate->bounce 2, escalate->escalate 58, escalate->file 9, file->bounce 6, file->file 160; scope: bounce->bounce 110, bounce->file 15, escalate->escalate 60, escalate->file 9, file->file 166; full: bounce->bounce 110, bounce->escalate 15, escalate->escalate 69, file->escalate 13, file->file 153
