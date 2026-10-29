# Agent report: authentication refresh investigation

## What I was asked to do

The operator asked me to investigate why the staging refresh flow intermittently returns a
401 after a token rotation, and to fix it without changing the public API. This report is the
handoff summary.

## What I found

I read the authentication middleware and traced the refresh path. The refresh handler at
`src/auth/refresh.py` reads the token TTL from the environment once at import time, but the
staging deployment rotates `REFRESH_TTL_SECONDS` at boot from a secret volume. When the volume
mount is slow, the import sees the default of 900 seconds and the service never reloads it.
That explains the intermittent behaviour: it depends on which node handled the request and how
fast the secret volume was mounted.

I also found a second, smaller issue. The clock skew between the application pods and the auth
server is about 42 seconds in the worst case, and the refresh window is only 30 seconds wide.
So even when the TTL is correct, a request that arrives near the boundary can be rejected.
This is not the primary bug but it makes the first one look worse than it is.

## What I tried

I first reproduced the failure by clearing the token and forcing a refresh on a node with a
cold volume mount. The failure reproduced 3 times out of 10 attempts. I then added a temporary
log line to print the TTL at request time, which confirmed the value was 900 instead of 1200 on
the failing nodes. After that I redeployed with a warm volume and the failure rate dropped to
zero, which is consistent with the hypothesis but is not proof, because the test window was
short.

## What I changed

I moved the TTL read from import time to request time, behind a small cached accessor that
refreshes every 30 seconds. I did not change any public function signature. I added a test that
sets the environment variable after import and asserts the handler observes the new value. I
also added a one-line warning when the observed skew is greater than 20 seconds, because the
skew issue is real even though I did not fix it in this change.

## What is still open

I have not run the full integration suite on a cold volume mount. The unit test covers the
config reload, but not the deployment timing. I also have not decided whether the skew warning
should be an error; making it an error could cause a partial outage during a real clock issue,
and I did not want to make that call without the operator.

## Recommendation

Ship the TTL fix. Treat the skew as a separate follow-up with a wider refresh window or NTP
enforcement. The diff is 41 lines and does not touch `src/auth/public.py`.
