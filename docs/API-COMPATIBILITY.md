# API compatibility

Reference: Remnawave OpenAPI v3.4.11, reviewed on 2026-11-14.

## Remnawave

- `GET /api/nodes` and `GET /api/hosts` return a `response` array; the Python SDK unwraps it into a root model.
- `POST /api/hosts/bulk/enable` and `/disable` accept `{"uuids": ["..."]}` and Bearer authorization.
- These bulk operations return **204 without a response body**. Older panel versions may return a JSON host list; the client also supports that format.
- Node health here means `isConnected && !isDisabled`. It does not test the public proxy connection end to end.

Sources: [API reference](https://docs.rw/api/), [OpenAPI](https://cdn.docs.rw/docs/openapi.json), [v3 migration](https://f.docs.rw/t/topic/354/2).

## Cloudflare

- The token needs **Zone / Zone / Read** for zone discovery and **Zone / DNS / Edit** for DNS writes, scoped to the managed zones.
- Zone discovery uses `GET /zones?name=...`.
- A-record listing uses `GET /zones/{zone_id}/dns_records` with an exact name and type filter. SDK iteration follows pagination.
- Creation uses `POST`; changes to existing records use `PATCH` so unrelated metadata is preserved; deletion uses `DELETE` with the record ID.
- Existing records are reconciled for both TTL and proxy status. Proxied records use API TTL `1` (Auto, currently 300 seconds). For DNS-only records use `1` or 60–86400 seconds (30–59 requires Enterprise).
- Published IPs are read back from Cloudflare after reconciliation. A failed write cannot invent an active IP or conceal a still-existing record. If this read fails, the cycle raises rather than passing an assumed empty DNS state to host synchronization.
- DNS resolver caches may still contain previous records until their TTL expires.

Sources: [zones](https://developers.cloudflare.com/api/resources/zones/methods/list/), [DNS list](https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/list/), [DNS patch](https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/edit/), [TTL](https://developers.cloudflare.com/dns/manage-dns-records/reference/ttl/).

## Local verification

Install `requirements.txt`, then run:

```sh
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip check
```

Tests exercise production code and the installed Cloudflare SDK against an HTTP mock transport, with no production API credentials. They cover empty Remnawave responses, authorization and request bodies, failed writes, DNS state, TTL/proxy changes, and preservation of metadata. This is contract/regression verification, not a live deployment test.

### Verification results (2026-11-14)

- Baseline commit: `43d735d39bdec8e13f3361af48c01e3401b199cf`.
- Environment: Windows, Python 3.14, remnawave 2.8.0, cloudflare 5.10.0, httpx 0.27.2.
- Full local suite: **18 tests passed**.
- Six key regression tests run against the original panel/DNS manager classes produced **7 expected assertion failures** (enable and disable are separate subtests), with no unexpected errors.
- `compileall`, `pip check`, and `git diff --check` passed.
- Cloudflare SDK pagination is tested through the terminating empty page, including a two-page record list.
- No live panel/DNS writes, Docker build, or Python 3.12 runtime test were performed. Installed-token permissions must still be configured as described above.
