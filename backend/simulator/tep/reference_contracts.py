"""Read-only prerecorded simulation records; never a TEP execution result."""
from typing import Literal

from pydantic import Field

from backend.contracts import StrictModel, TEPVariable


class ReferenceMetadata(StrictModel):
    schema_version: Literal["tep-reference-1.0"] = "tep-reference-1.0"
    profile_id: Literal["local-tep-52vars-20261009"] = "local-tep-52vars-20261009"
    data_origin: Literal["simulation"] = "simulation"
    record_kind: Literal["prerecorded_reference"] = "prerecorded_reference"
    used_for_approval: Literal[False] = False
    field_validation: Literal["not_performed_no_measured_data"] = "not_performed_no_measured_data"
    source_url: None = None
    source_version_status: Literal["unverified_local_upload"] = "unverified_local_upload"
    license_status: Literal["bundled_code_notice_present_dataset_scope_unverified"] = "bundled_code_notice_present_dataset_scope_unverified"
    source_files_sha256: dict[str, str]
    column_order: list[str]
    timestamp_status: Literal["absent"] = "absent"
    sample_period_s: None = None
    inferred_sample_period_s: Literal[180] = 180
    sample_period_status: Literal["bundled_code_only_unverified_per_file"] = "bundled_code_only_unverified_per_file"
    controller: Literal["bundled_closed_loop_per_file_unverified"] = "bundled_closed_loop_per_file_unverified"
    random_seed: None = None
    operating_mode: None = None
    initial_state: None = None
    fault_onset_sample: None = None
    comparison_status: Literal["not_matched_to_current_open_loop_run"] = "not_matched_to_current_open_loop_run"
    limitation: str


class ReferenceVariable(TEPVariable):
    column_index: int = Field(ge=0, le=51)
    definition_source: Literal["bundled_teprob.f.txt_and_readme.txt"] = "bundled_teprob.f.txt_and_readme.txt"


class ReferenceFile(StrictModel):
    file_id: str
    condition: Literal["normal", "fault"]
    fault_index: int | None = Field(default=None, ge=1, le=21)
    split: Literal["training", "test"]
    observation_count: int = Field(gt=0)
    stored_layout: Literal["observations_by_variables", "variables_by_observations"]
    sha256: str
    present: bool


class ReferenceCatalog(StrictModel):
    metadata: ReferenceMetadata
    variables: dict[str, ReferenceVariable]
    files: list[ReferenceFile]


class ReferenceStatistics(StrictModel):
    minimum: float
    maximum: float
    mean: float


class ReferenceSeries(StrictModel):
    metadata: ReferenceMetadata
    file: ReferenceFile
    variable: str
    definition: ReferenceVariable
    sample_indices: list[int]
    values: list[float]
    statistics: ReferenceStatistics
