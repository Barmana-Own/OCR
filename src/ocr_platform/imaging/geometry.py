"""Coordinate mappings for derived OCR images.

Mappings are expressed as homogeneous projective matrices.  The common crop,
scale, and rotation cases are affine, but retaining a 3x3 matrix means a
future perspective/dewarping adapter can preserve a real mapping rather than
silently dropping provenance.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from ocr_platform.errors import InvalidDocumentError

Matrix3x3 = tuple[float, float, float, float, float, float, float, float, float]
Point = tuple[float, float]
IDENTITY_MATRIX: Matrix3x3 = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def multiply_matrices(left: Matrix3x3, right: Matrix3x3) -> Matrix3x3:
    """Return ``left @ right`` for row-major homogeneous matrices."""

    return tuple(
        sum(left[row * 3 + index] * right[index * 3 + column] for index in range(3))
        for row in range(3)
        for column in range(3)
    )  # type: ignore[return-value]


def apply_matrix(matrix: Matrix3x3, point: Point) -> Point:
    x, y = point
    denominator = matrix[6] * x + matrix[7] * y + matrix[8]
    if abs(denominator) < 1e-12:
        raise InvalidDocumentError("coordinate mapping is singular at the requested point")
    return (
        (matrix[0] * x + matrix[1] * y + matrix[2]) / denominator,
        (matrix[3] * x + matrix[4] * y + matrix[5]) / denominator,
    )


def _validate_matrix(matrix: Matrix3x3) -> Matrix3x3:
    if len(matrix) != 9 or not all(math.isfinite(value) for value in matrix):
        raise InvalidDocumentError("coordinate mapping matrix must contain nine finite values")
    return tuple(float(value) for value in matrix)  # type: ignore[return-value]


def crop_mapping(left: float, top: float, width: int, height: int) -> Matrix3x3:
    if width <= 0 or height <= 0 or left < 0 or top < 0:
        raise InvalidDocumentError("crop mapping dimensions must be positive")
    return (1.0, 0.0, float(left), 0.0, 1.0, float(top), 0.0, 0.0, 1.0)


def scale_mapping(scale_x: float, scale_y: float | None = None) -> Matrix3x3:
    if scale_x <= 0:
        raise InvalidDocumentError("scale must be positive")
    scale_y = scale_x if scale_y is None else scale_y
    if scale_y <= 0:
        raise InvalidDocumentError("scale must be positive")
    return (1.0 / scale_x, 0.0, 0.0, 0.0, 1.0 / scale_y, 0.0, 0.0, 0.0, 1.0)


def rotation_output_to_input(angle_degrees: float, width: int, height: int) -> Matrix3x3:
    """Return the output-to-input mapping for Pillow's non-expanding rotation."""

    if width <= 0 or height <= 0:
        raise InvalidDocumentError("rotation mapping dimensions must be positive")
    if not math.isfinite(angle_degrees):
        raise InvalidDocumentError("rotation angle must be finite")
    radians = math.radians(-angle_degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    return (
        cosine,
        -sine,
        center_x - cosine * center_x + sine * center_y,
        sine,
        cosine,
        center_y - sine * center_x - cosine * center_y,
        0.0,
        0.0,
        1.0,
    )


def homography_from_correspondences(source: Iterable[Point], target: Iterable[Point]) -> Matrix3x3:
    """Build a projective matrix mapping ``source`` points to ``target`` points.

    Four non-collinear point pairs are sufficient.  A small deterministic
    Gaussian eliminator avoids making NumPy a mandatory runtime dependency.
    """

    source_points = tuple(source)
    target_points = tuple(target)
    if len(source_points) != 4 or len(target_points) != 4:
        raise InvalidDocumentError("perspective mapping requires four point pairs")
    rows: list[list[float]] = []
    for (x, y), (u, v) in zip(source_points, target_points, strict=True):
        rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, u])
        rows.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y, v])
    values = _solve_linear_system(rows)
    matrix = (*values[:8], 1.0)
    return _validate_matrix(matrix)  # type: ignore[arg-type]


def _solve_linear_system(rows: list[list[float]]) -> list[float]:
    if len(rows) != 8 or any(len(row) != 9 for row in rows):
        raise InvalidDocumentError("coordinate mapping system has an invalid shape")
    augmented = [row[:] for row in rows]
    for column in range(8):
        pivot = max(range(column, 8), key=lambda index: abs(augmented[index][column]))
        pivot_value = augmented[pivot][column]
        if abs(pivot_value) < 1e-10:
            raise InvalidDocumentError("perspective mapping points are degenerate")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(8):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [
                    current - factor * pivot_value_value
                    for current, pivot_value_value in zip(
                        augmented[row], augmented[column], strict=True
                    )
                ]
    return [augmented[index][8] for index in range(8)]


@dataclass(frozen=True, slots=True)
class CoordinateMapping:
    """Mapping from a derived image back to its original source image/page."""

    source_width: int
    source_height: int
    output_width: int
    output_height: int
    output_to_source: Matrix3x3 = IDENTITY_MATRIX
    source_to_page: Matrix3x3 = IDENTITY_MATRIX
    source_coordinate_space: str = "rendered_pixel"
    page_coordinate_space: str = "rendered_pixel"
    page_width: float | None = None
    page_height: float | None = None

    def __post_init__(self) -> None:
        if min(self.source_width, self.source_height, self.output_width, self.output_height) <= 0:
            raise InvalidDocumentError("mapping dimensions must be positive")
        _validate_matrix(self.output_to_source)
        _validate_matrix(self.source_to_page)
        if not self.source_coordinate_space or not self.page_coordinate_space:
            raise InvalidDocumentError("mapping coordinate spaces must be named")

    @classmethod
    def identity(
        cls,
        width: int,
        height: int,
        *,
        page_reference_size: tuple[float, float] | None = None,
        source_coordinate_space: str = "rendered_pixel",
        page_coordinate_space: str = "rendered_pixel",
    ) -> CoordinateMapping:
        return cls.for_source(
            source_width=width,
            source_height=height,
            output_width=width,
            output_height=height,
            page_reference_size=page_reference_size,
            source_coordinate_space=source_coordinate_space,
            page_coordinate_space=page_coordinate_space,
        )

    @classmethod
    def for_source(
        cls,
        *,
        source_width: int,
        source_height: int,
        output_width: int,
        output_height: int,
        output_to_source: Matrix3x3 = IDENTITY_MATRIX,
        page_reference_size: tuple[float, float] | None = None,
        source_to_page: Matrix3x3 | None = None,
        source_coordinate_space: str = "rendered_pixel",
        page_coordinate_space: str = "rendered_pixel",
    ) -> CoordinateMapping:
        if min(source_width, source_height, output_width, output_height) <= 0:
            raise InvalidDocumentError("mapping dimensions must be positive")
        page_width = page_height = None
        if page_reference_size is not None:
            page_width, page_height = page_reference_size
            if page_width <= 0 or page_height <= 0:
                raise InvalidDocumentError("page reference dimensions must be positive")
            if source_to_page is None:
                source_to_page = (
                    page_width / source_width,
                    0.0,
                    0.0,
                    0.0,
                    page_height / source_height,
                    0.0,
                    0.0,
                    0.0,
                    1.0,
                )
        return cls(
            source_width=source_width,
            source_height=source_height,
            output_width=output_width,
            output_height=output_height,
            output_to_source=_validate_matrix(output_to_source),
            source_to_page=_validate_matrix(source_to_page or IDENTITY_MATRIX),
            source_coordinate_space=source_coordinate_space,
            page_coordinate_space=page_coordinate_space,
            page_width=page_width,
            page_height=page_height,
        )

    def compose(self, local: CoordinateMapping) -> CoordinateMapping:
        """Compose a local output-to-current mapping into this cumulative mapping."""

        if (local.source_width, local.source_height) != (self.output_width, self.output_height):
            raise InvalidDocumentError("coordinate mappings do not share a source/output size")
        return CoordinateMapping(
            source_width=self.source_width,
            source_height=self.source_height,
            output_width=local.output_width,
            output_height=local.output_height,
            output_to_source=multiply_matrices(self.output_to_source, local.output_to_source),
            source_to_page=self.source_to_page,
            source_coordinate_space=self.source_coordinate_space,
            page_coordinate_space=self.page_coordinate_space,
            page_width=self.page_width,
            page_height=self.page_height,
        )

    def map_point_to_source(self, point: Point) -> Point:
        return apply_matrix(self.output_to_source, point)

    def map_point_to_page(self, point: Point) -> Point:
        return apply_matrix(
            multiply_matrices(self.source_to_page, self.output_to_source), point
        )

    def map_bbox_to_source(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return _bounds(self.map_point_to_source(point) for point in _bbox_points(bbox))

    def map_bbox_to_page(
        self, bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return _bounds(self.map_point_to_page(point) for point in _bbox_points(bbox))

    def map_polygon_to_source(self, polygon: Iterable[Point]) -> tuple[Point, ...]:
        return tuple(self.map_point_to_source(point) for point in polygon)

    def map_polygon_to_page(self, polygon: Iterable[Point]) -> tuple[Point, ...]:
        return tuple(self.map_point_to_page(point) for point in polygon)

    def as_dict(self) -> dict[str, object]:
        return {
            "source_width": self.source_width,
            "source_height": self.source_height,
            "output_width": self.output_width,
            "output_height": self.output_height,
            "output_to_source": list(self.output_to_source),
            "source_to_page": list(self.source_to_page),
            "source_coordinate_space": self.source_coordinate_space,
            "page_coordinate_space": self.page_coordinate_space,
            "page_width": self.page_width,
            "page_height": self.page_height,
        }


def _bbox_points(bbox: tuple[float, float, float, float]) -> tuple[Point, ...]:
    x0, y0, x1, y1 = bbox
    if not all(math.isfinite(value) for value in bbox):
        raise InvalidDocumentError("bbox coordinates must be finite")
    if x1 < x0 or y1 < y0:
        raise InvalidDocumentError("bbox coordinates must be ordered")
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def _bounds(points: Iterable[Point]) -> tuple[float, float, float, float]:
    values = tuple(points)
    if not values:
        raise InvalidDocumentError("cannot map an empty geometry")
    return (
        min(point[0] for point in values),
        min(point[1] for point in values),
        max(point[0] for point in values),
        max(point[1] for point in values),
    )
