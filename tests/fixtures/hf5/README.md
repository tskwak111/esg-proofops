# Retry reservation fixture

`hyundai-preliminary-retry.json` preserves a request and the minimal response/usage
shape needed to reproduce output-budget exhaustion followed by a retry. The
source hash and policy identity bind the fixture. Tests replace HTTP and preserve
reservation and settlement assertions. No credentials or authorization grants are
included; this offline fixture does not establish model quality.
