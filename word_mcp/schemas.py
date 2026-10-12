from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReplaceText(StrictModel):
    op: Literal["replace_text"]
    target: str = Field(min_length=1, max_length=80)
    old: str = Field(min_length=1, max_length=20000)
    new: str = Field(max_length=20000)
    occurrence: int = Field(default=0, ge=0, le=1000)


class AddParagraph(StrictModel):
    op: Literal["add_paragraph"]
    text: str = Field(max_length=20000)
    after: str | None = None
    style: Literal["Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "List Bullet", "List Number"] = "Normal"


class FormatParagraph(StrictModel):
    op: Literal["format_paragraph"]
    target: str
    bold: bool | None = None
    italic: bool | None = None
    size_pt: float | None = Field(default=None, ge=6, le=72)


class AddTable(StrictModel):
    op: Literal["add_table"]
    rows: list[list[str]] = Field(min_length=1, max_length=100)


class AddPicture(StrictModel):
    op: Literal["add_picture"]
    image_path: str
    width_cm: float = Field(default=12.0, ge=0.5, le=25)
    after: str | None = None
    alt_text: str = Field(default="", max_length=2000)


class ReplacePicture(StrictModel):
    op: Literal["replace_picture"]
    image_id: str
    image_path: str


Operation = Annotated[
    ReplaceText | AddParagraph | FormatParagraph | AddTable | AddPicture | ReplacePicture,
    Field(discriminator="op"),
]


class EditPlan(StrictModel):
    summary: str = Field(max_length=2000)
    operations: list[Operation] = Field(max_length=100)


class TextEditPlan(StrictModel):
    summary: str = Field(max_length=2000)
    operations: list[Annotated[ReplaceText | AddParagraph, Field(discriminator="op")]] = Field(max_length=100)


class ImageAnalysis(StrictModel):
    description: str = Field(max_length=8000, description="Describe visible objects and colors in Russian")
    visible_text: str = Field(max_length=16000, description="Copy ALL visible letters and numbers verbatim; empty string if none are readable")
    suggested_caption: str = Field(max_length=2000, description="A short Russian caption")
    uncertainty: str = Field(max_length=2000, description="State any unreadable text or ambiguity in Russian; empty string if none")
