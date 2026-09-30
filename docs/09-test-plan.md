# Software Test Plan

## Scope

The 0.1.0 test strategy covers canonical schema invariants, Persian normalization, bounded ingestion/storage, native-first PDF routing, OCR adapter/verification behavior, preprocessing retries, deterministic dataset exports, API authentication/upload boundaries, and security regressions.

## Risk-based matrix

| Requirement/risk | Test level | Coverage |
|---|---|---|
| FR-001/FR-004 | integration | native PDF and image reader/pipeline tests |
| FR-002/FR-015/FR-020 | unit/integration | canonical models, storage, source and verification history tests |
| FR-005/FR-011/FR-012 | unit/integration | render policy, crop geometry, retry/preprocessing tests |
| FR-006/FR-007/FR-008 | unit | router and typed backend result tests |
| FR-009/FR-010/NFR-007 | unit | raw/normalized and mixed Persian/English and mixed native/image PDF fixtures |
| FR-013/FR-014 | unit | consensus, low-confidence, disagreement and missing-backend tests |
| FR-016/NFR-001 | integration | deterministic JSON/text/Markdown/crop export tests |
| FR-018/NFR-003/NFR-008 | API/security | auth, request ID, upload limit and safe error tests |
| NFR-004/NFR-005 | security/review | logging, bounds, traversal and subprocess review |
| NFR-010 | build/CI | package build, compile, lint, test and deployment configuration review |

## Test boundaries

External OCR/model services are not mocked in production code. Deterministic backend doubles are used only in unit/integration tests. Real Tesseract execution and optional PaddleOCR/HTR/layout model validation require separately installed binaries, model weights, and licensing decisions; those checks remain explicitly `NOT_RUN` in the results when unavailable.

