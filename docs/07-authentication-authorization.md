# Authentication and Authorization

## Identity model

Release 0.1.0 protects operational processing endpoints with configured service API keys. Health and readiness are intentionally public but reveal only safe status/version fields. Human identity, tenant identity, user sessions, MFA, and review-level authorization are deferred until a multi-user review service is introduced.

## Authentication mechanism

Keys are supplied through the X-OCR-API-Key header and loaded from OCR_API_KEYS as a semicolon-delimited environment value. Comparisons use constant-time equality. No key is stored in source, logged, returned in errors, or placed in URLs.

## Authorization matrix

| Operation | Public | Service key |
|---|---:|---:|
| GET /healthz | yes | yes |
| GET /readyz | yes | yes |
| POST /v1/documents | no when OCR_REQUIRE_AUTH=true | yes |
| GET /v1/jobs/{job_id} | no when OCR_REQUIRE_AUTH=true | yes |
| GET /v1/documents/{document_id} and artifact/export routes | no when OCR_REQUIRE_AUTH=true | yes |
| POST /v1/documents/process | no when OCR_REQUIRE_AUTH=true | yes |

A future multi-user API must add object-level authorization for document/source/export/review resources and tenant isolation at the service/repository boundary.

## Lifecycle and abuse controls

API keys are static service credentials for the initial operational boundary. Staging and production configuration rejects disabled authentication or missing keys. Rotation is performed by replacing the environment value and restarting the service. Rate limiting and key-scoped quotas belong at the gateway/worker deployment layer and must be added before exposing the service publicly.

## Tests

The auth unit tests cover missing, invalid, and valid keys. The API tests cover public health and protected upload behavior. Auth failures use the same safe error envelope as processing failures.


