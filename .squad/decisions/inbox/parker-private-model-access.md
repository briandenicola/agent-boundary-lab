# Parker: private-only account model access (PROPOSED / UNVERIFIED, 2026-10-09)
Recommend option A: azapi outbound private-endpoint rule `foundry-account-pe` on the account's
managed network plus Network Connection Approver for the account identity. Allowlist host
unchanged and identical for both agents; no IPs/CIDRs. Brian must approve: the rule resource,
the role (and whether Contributor-at-RG is acceptable), possible cost. Not applied.
Rejected: public access (control surface), BYO-VNet (redesign). Details: compatibility.md B9g.
