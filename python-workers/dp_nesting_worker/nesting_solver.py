from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from geometry_extractor import PieceSpec


@dataclass(frozen=True)
class OrientedPiece:
    piece_index: int
    component_id: str
    name: str
    width_mm: int
    height_mm: int
    rotated: bool
    allow_rotation: bool
    area_mm2: int


@dataclass(frozen=True)
class RowLayout:
    mask: int
    row_height_mm: int
    row_width_mm: int
    items: tuple[OrientedPiece, ...]


@dataclass(frozen=True)
class Placement:
    component_id: str
    x_mm: int
    y_mm: int
    width_mm: int
    height_mm: int
    rotated: bool
    row_index: int

    def to_dict(self) -> dict[str, int | bool | str]:
        return {
            "componentId": self.component_id,
            "xMm": self.x_mm,
            "yMm": self.y_mm,
            "widthMm": self.width_mm,
            "heightMm": self.height_mm,
            "rotated": self.rotated,
            "rowIndex": self.row_index,
        }


@dataclass(frozen=True)
class NestingPlan:
    consumed_length_mm: int
    placements: tuple[Placement, ...]
    rows: tuple[RowLayout, ...]
    algorithm: str

    @property
    def total_part_area_mm2(self) -> int:
        return sum(placement.width_mm * placement.height_mm for placement in self.placements)


def solve_nesting(pieces: list[PieceSpec], fabric_width_mm: int, gap_mm: int) -> NestingPlan:
    if not pieces:
        return NestingPlan(0, tuple(), tuple(), "exact-shelf-dp")

    if len(pieces) <= 14:
        return _solve_exact_shelf_dp(pieces, fabric_width_mm, gap_mm)
    return _solve_greedy_shelf(pieces, fabric_width_mm, gap_mm)


def _solve_exact_shelf_dp(pieces: list[PieceSpec], fabric_width_mm: int, gap_mm: int) -> NestingPlan:
    piece_options = [_orientation_options(index, piece) for index, piece in enumerate(pieces)]
    all_mask = (1 << len(pieces)) - 1

    @lru_cache(maxsize=None)
    def best_row(mask: int) -> RowLayout | None:
        indices = [index for index in range(len(pieces)) if mask & (1 << index)]
        best_candidate: tuple[int, int, tuple[OrientedPiece, ...]] | None = None

        def backtrack(position: int, width_sum: int, max_height: int, chosen: list[OrientedPiece]) -> None:
            nonlocal best_candidate
            item_count = len(chosen)
            current_row_width = width_sum + gap_mm * max(0, item_count - 1)
            if current_row_width > fabric_width_mm:
                return
            if best_candidate is not None and max_height > best_candidate[0]:
                return
            if position == len(indices):
                candidate = (max_height, current_row_width, tuple(chosen))
                if best_candidate is None or candidate[:2] < best_candidate[:2]:
                    best_candidate = candidate
                return

            piece_index = indices[position]
            for option in piece_options[piece_index]:
                next_width_sum = width_sum + option.width_mm
                next_item_count = item_count + 1
                next_total_width = next_width_sum + gap_mm * max(0, next_item_count - 1)
                if next_total_width > fabric_width_mm:
                    continue
                chosen.append(option)
                backtrack(position + 1, next_width_sum, max(max_height, option.height_mm), chosen)
                chosen.pop()

        backtrack(0, 0, 0, [])
        if best_candidate is None:
            return None
        return RowLayout(mask, best_candidate[0], best_candidate[1], best_candidate[2])

    @lru_cache(maxsize=None)
    def best_length(mask: int) -> int:
        if mask == 0:
            return 0

        anchor = mask & -mask
        best_value: int | None = None
        submask = mask
        while submask:
            if submask & anchor:
                row = best_row(submask)
                if row is not None:
                    rest_mask = mask ^ submask
                    candidate = row.row_height_mm + (gap_mm if rest_mask else 0) + best_length(rest_mask)
                    if best_value is None or candidate < best_value:
                        best_value = candidate
            submask = (submask - 1) & mask

        if best_value is None:
            raise ValueError("No feasible shelf layout found for the given fabric width")
        return best_value

    rows: list[RowLayout] = []
    mask = all_mask
    while mask:
        anchor = mask & -mask
        chosen_row: RowLayout | None = None
        chosen_rest_mask = 0
        submask = mask
        while submask:
            if submask & anchor:
                row = best_row(submask)
                if row is not None:
                    rest_mask = mask ^ submask
                    candidate = row.row_height_mm + (gap_mm if rest_mask else 0) + best_length(rest_mask)
                    if candidate == best_length(mask):
                        if chosen_row is None or (row.row_height_mm, row.row_width_mm) < (
                            chosen_row.row_height_mm,
                            chosen_row.row_width_mm,
                        ):
                            chosen_row = row
                            chosen_rest_mask = rest_mask
            submask = (submask - 1) & mask

        if chosen_row is None:
            raise ValueError("Failed to reconstruct exact nesting plan")
        rows.append(chosen_row)
        mask = chosen_rest_mask

    placements = _materialize_rows(rows, gap_mm)
    return NestingPlan(best_length(all_mask), placements, tuple(rows), "exact-shelf-dp")


def _solve_greedy_shelf(pieces: list[PieceSpec], fabric_width_mm: int, gap_mm: int) -> NestingPlan:
    rows: list[list[OrientedPiece]] = []
    row_heights: list[int] = []
    row_widths: list[int] = []

    sortable = sorted(
        enumerate(pieces),
        key=lambda item: (max(item[1].width_mm, item[1].height_mm), item[1].area_mm2),
        reverse=True,
    )

    for index, piece in sortable:
        best_choice: tuple[int, int, OrientedPiece] | None = None
        for option in _orientation_options(index, piece):
            placed = False
            for row_index, row_items in enumerate(rows):
                width_if_added = row_widths[row_index] + (gap_mm if row_items else 0) + option.width_mm
                if width_if_added > fabric_width_mm:
                    continue
                new_row_height = max(row_heights[row_index], option.height_mm)
                score = (new_row_height - row_heights[row_index], width_if_added)
                if best_choice is None or score < best_choice[:2]:
                    best_choice = (score[0], score[1], option)
                    best_row_index = row_index
                    placed = True
            if placed:
                continue
            if option.width_mm <= fabric_width_mm:
                score = (option.height_mm + 1_000_000, option.width_mm)
                if best_choice is None or score < best_choice[:2]:
                    best_choice = (score[0], score[1], option)
                    best_row_index = len(rows)

        if best_choice is None:
            raise ValueError(f"Component '{piece.component_id}' is wider than the fabric roll")

        option = best_choice[2]
        if best_row_index == len(rows):
            rows.append([option])
            row_heights.append(option.height_mm)
            row_widths.append(option.width_mm)
        else:
            if rows[best_row_index]:
                row_widths[best_row_index] += gap_mm
            rows[best_row_index].append(option)
            row_widths[best_row_index] += option.width_mm
            row_heights[best_row_index] = max(row_heights[best_row_index], option.height_mm)

    row_layouts = tuple(
        RowLayout(
            mask=0,
            row_height_mm=row_heights[row_index],
            row_width_mm=row_widths[row_index],
            items=tuple(row_items),
        )
        for row_index, row_items in enumerate(rows)
    )
    placements = _materialize_rows(list(row_layouts), gap_mm)
    total_length = 0
    for row_index, row in enumerate(row_layouts):
        total_length += row.row_height_mm
        if row_index < len(row_layouts) - 1:
            total_length += gap_mm
    return NestingPlan(total_length, placements, row_layouts, "greedy-shelf")


def _materialize_rows(rows: list[RowLayout] | tuple[RowLayout, ...], gap_mm: int) -> tuple[Placement, ...]:
    placements: list[Placement] = []
    y_mm = 0
    for row_index, row in enumerate(rows):
        x_mm = 0
        ordered_items = sorted(row.items, key=lambda item: (-item.height_mm, -item.width_mm, item.component_id))
        for item in ordered_items:
            placements.append(
                Placement(
                    component_id=item.component_id,
                    x_mm=x_mm,
                    y_mm=y_mm,
                    width_mm=item.width_mm,
                    height_mm=item.height_mm,
                    rotated=item.rotated,
                    row_index=row_index,
                )
            )
            x_mm += item.width_mm + gap_mm
        y_mm += row.row_height_mm
        if row_index < len(rows) - 1:
            y_mm += gap_mm
    return tuple(placements)


def _orientation_options(piece_index: int, piece: PieceSpec) -> tuple[OrientedPiece, ...]:
    options = [
        OrientedPiece(
            piece_index=piece_index,
            component_id=piece.component_id,
            name=piece.name,
            width_mm=piece.width_mm,
            height_mm=piece.height_mm,
            rotated=False,
            allow_rotation=piece.allow_rotation,
            area_mm2=piece.area_mm2,
        )
    ]
    if piece.allow_rotation and piece.width_mm != piece.height_mm:
        options.append(
            OrientedPiece(
                piece_index=piece_index,
                component_id=piece.component_id,
                name=piece.name,
                width_mm=piece.height_mm,
                height_mm=piece.width_mm,
                rotated=True,
                allow_rotation=piece.allow_rotation,
                area_mm2=piece.area_mm2,
            )
        )
    return tuple(options)