# Stratus: Business Requirements Document

Oct 26, 2026

## 1. Purpose and background

Stratus lets an organization find wasted cloud spend across AWS, Azure and GCP, decide what to do about it, and prove the savings afterwards. This document states the business requirements the application must meet.

**The problem.** Cloud bills grow because idle and oversized virtual machines go unnoticed, accounts are spread across teams and providers, and nobody can show whether a cost-saving change actually reduced spend. Existing tools either stop at a list of tips or need broad write access to the cloud.

**The solution.** One shared workspace that reads each cloud account with read-only access, recommends changes with evidence, records who approved what, and checks later data to confirm the saving. Stratus never changes a cloud resource itself.

## 2. Business objectives

| # | Objective | How we will know |
| --- | --- | --- |
| O1 | Reduce wasted compute spend | Potential and verified monthly savings shown per account and in total |
| O2 | Give one view across clouds and accounts | Spend, savings and health for AWS, Azure and GCP on one dashboard |
| O3 | Make savings credible | Every implemented change is checked against later data and marked Verified or Not verified |
| O4 | Keep teams accountable | Every approval, change and sign-in is recorded with the person's email |
| O5 | Catch problems early | Monitor flags failed syncs, stale data, resource pressure and budget overruns, each with fix steps |
| O6 | Stay safe by default | Read-only cloud access, encrypted credentials, no automatic changes |

## 3. Stakeholders and users

| Role | Needs from Stratus |
| --- | --- |
| Cloud / FinOps lead | Connect accounts, set budgets, track savings, share a report |
| Engineer / service owner | See evidence for their VMs, approve or dismiss, mark changes done |
| Leadership | A one-page view of spend, savings and risk |
| Organization admin | Create the organization, add and remove members, rename the organization |
| Platform administrator | Install, configure sessions and sync, keep credentials safe |

Each user belongs to exactly one organization and is an `admin` or a `member`. Members can do everything except manage members and rename the organization.

## 4. Scope

**In scope**

- Virtual machines (compute) on AWS, Azure and GCP
- Multiple organizations, each isolated from the others, with email and password sign-in and `admin` / `member` roles
- Read-only collection for AWS and Azure; JSON import for any source
- Recommendations, approvals, savings verification, monitoring, budgets, comparison and reporting

**Out of scope for this release**

- Changing, stopping or deleting any cloud resource
- Storage, databases, networking, licenses and commitment discounts
- Invoice or billing-export reconciliation
- Single sign-on, email verification and password reset
- A live GCP collector

## 5. Business requirements

Priority uses Must, Should, Could. Status is where the build stands today.

| ID | Requirement | Priority | Status |
| --- | --- | --- | --- |
| BR-01 | Users sign in with email and password. Anyone can create an organization and becomes its admin; admins add and remove members | Must | Delivered |
| BR-02 | Connect several AWS, Azure and GCP accounts, each tracked and budgeted separately | Must | Delivered |
| BR-03 | Collect VM inventory and 14 days of metrics from AWS and Azure with read-only access, on a schedule and on demand | Must | Delivered; tested with simulated cloud responses only |
| BR-04 | Offer a demo account that needs no credentials and is clearly labelled | Should | Delivered |
| BR-05 | Accept inventory by JSON file for any source, including GCP | Must | Delivered |
| BR-06 | Recommend stopping idle VMs and resizing oversized VMs, with evidence, risk and monthly saving. Never suggest stopping a production or critical VM | Must | Delivered |
| BR-07 | Show how confident each recommendation is, based on recent readings | Should | Delivered |
| BR-08 | Let members approve, dismiss, simulate and mark a change implemented. Reject decisions based on outdated evidence | Must | Delivered |
| BR-09 | Verify each implemented change from later data and report verified savings | Must | Delivered |
| BR-10 | One dashboard with spend and savings by cloud, account and environment, plus a run-rate trend | Must | Delivered |
| BR-11 | Monitor for failed syncs, stale data, resource pressure, unusual changes and missing metrics, each with fix steps | Must | Delivered |
| BR-12 | Set a monthly budget per account and warn at 90% and 100% | Should | Delivered |
| BR-13 | Compare equivalent VM sizes and list prices across the three clouds | Should | Delivered |
| BR-14 | Produce a printable one-page executive report | Should | Delivered |
| BR-15 | Record sign-ins, syncs, imports, decisions and account changes with the person's email | Must | Delivered |
| BR-16 | Removed (was an inventory and event integration with an external tool; no longer part of the application) | n/a | Removed |
| BR-17 | Answer plain-language questions from the organization's own data | Could | Delivered |
| BR-18 | Live GCP collector | Could | Not started |
| BR-19 | Each organization has its own accounts, credentials, resources, recommendations, savings ledger, audit log, history and budgets, and cannot see another organization's data | Must | Delivered; isolation covered by automated tests |

## 6. Non-functional requirements

| Area | Requirement |
| --- | --- |
| Security | Cloud access is read-only. Cloud credentials are encrypted at rest and never shown again. Passwords are hashed with scrypt. Sessions are random tokens stored hashed, tied to a user, and expire after 12 hours by default. Five wrong passwords lock an email for 10 minutes. Organizations are isolated from each other |
| Safety | No automatic changes to cloud resources. Untagged VMs are treated as Production. Missing metrics withhold savings |
| Accuracy | Savings are estimates from on-demand list prices, labelled as such. Verified means a later reading shows the cost fell |
| Reliability | A failed sync is recorded with a safe message and retried on the next schedule. Imports apply fully or not at all |
| Data | Metric history is kept for 90 days. Up to 500 resources per import and 50 accounts |
| Usability | Works on desktop and phone widths. Text meets common contrast and size guidance |
| Auditability | Every action is attributed to a person's email and kept in the activity log |

## 7. Assumptions, constraints and dependencies

**Assumptions**

- The organization can create a read-only identity in each cloud account it connects
- VMs are tagged with Environment, Owner and Critical where possible
- Guest memory metrics are enabled (CloudWatch agent, Azure Monitor Agent), otherwise savings are withheld

**Constraints**

- Basic accounts only: no email verification, password reset or single sign-on; an admin sets passwords for members they add
- Sign-up is open to anyone who can reach the API, and rate limiting is in memory per process
- Compute only, priced at approximate on-demand list prices
- Live collectors cover AWS and Azure; GCP uses import

**Dependencies**

- PostgreSQL database and a stored encryption key for credentials (losing the key means re-entering credentials)
- Network access from the server to AWS and Azure APIs for live accounts

## 8. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Live collectors behave differently on a real account than in testing | Wrong or missing data | Run Test and Sync now on a non-production account first |
| Open sign-up or a guessed password gives unwanted access | Unwanted organizations or access to one organization | Passwords hashed, lockout after five wrong attempts; add email verification, restrict sign-up, move to single sign-on |
| List prices differ from the real bill | Savings overstated or understated | Label figures as estimates; add billing reconciliation later |
| A stopped VM was actually needed | Service disruption | Show evidence and risk, never suggest stopping production, require approval and a person to act |
| Encryption key is lost | Stored credentials unusable | Back up the key with the database |
| Missing guest metrics | No recommendations for some VMs | Monitor flags the gap with steps to enable the agent |

## 9. Acceptance criteria

- [ ] A user creates an organization or signs in with email and password; a wrong password is refused and repeated failures lock the email
- [ ] A user in one organization cannot see or change another organization's data
- [ ] An administrator adds an AWS or Azure account, presses Test and Sync now, and sees its VMs within one minute
- [ ] A demo account appears with a fleet and history without any credentials
- [ ] Each recommendation shows evidence, risk, estimated saving and confidence
- [ ] An approved change can be marked implemented, and the next sync marks it Verified or Not verified
- [ ] Re-syncing does not erase an approval when only routine metrics move
- [ ] The Monitor lists a failed sync, a stale resource and an over-budget account, each with fix steps
- [ ] Credentials are never shown after they are saved
- [ ] The executive report prints to one clear page
- [ ] Every sign-in, sync, decision and account change appears in the activity log with an email

## 10. Current status and next steps

17 of 18 active requirements are built (BR-16 was removed and BR-18 is not started), and 58 automated tests pass on in-memory SQLite, including tenant isolation tests. The multi-organization migration was also verified on a clone of a real PostgreSQL database. Sign-in, accounts, demo sync, approvals, the savings ledger, Ask and the report were also exercised in a browser.

**Not yet proven**

- Live AWS and Azure collectors against a real account (tested with simulated responses only)
- The LLM provider path against a live provider

**Next steps**

1. Run the AWS or Azure collector on a non-production account and fix what surfaces
2. Add email verification, password reset and single sign-on; restrict or approve sign-ups
3. Reconcile savings with billing exports
4. Add a live GCP collector (BR-18)
