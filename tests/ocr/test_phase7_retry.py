from ocr_platform.ocr.verification.retry import RetryPlan, RetryStage


def test_retry_plan_is_ordered_and_bounded() -> None:
    plan = RetryPlan(
        max_attempts=6,
        alternate_preprocessing_variants=("grayscale", "contrast"),
        region_scales=(2, 3, 4),
        high_quality_dpi=450,
        tiny_text_dpi=600,
    ).build(tiny_text=True, backend_count=2)

    assert len(plan) == 6
    assert plan[0].stage == RetryStage.FIRST_PASS
    assert plan[0].preprocess_variant == "source-render"
    assert plan[1].stage == RetryStage.ALTERNATE_PREPROCESSING
    assert plan[2].stage == RetryStage.ALTERNATE_PREPROCESSING
    assert plan[3].stage == RetryStage.HIGHER_RESOLUTION
    assert plan[3].dpi == 600
    assert plan[4].stage == RetryStage.ALTERNATE_SCALE
    assert plan[4].region_scale == 2
    assert plan[5].stage == RetryStage.ALTERNATE_BACKEND
    assert plan[5].backend_index == 1


def test_retry_plan_never_generates_attempts_past_budget() -> None:
    plan = RetryPlan(max_attempts=2).build(tiny_text=False, backend_count=8)

    assert len(plan) == 2
    assert [item.backend_index for item in plan] == [0, 0]
