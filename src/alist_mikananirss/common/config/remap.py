from pydantic import BaseModel, Field


class RemapConfig(BaseModel):
    enable: bool = Field(default=False, description="Enable remapping")
    cfg_path: str = Field(
        default="./remap.yaml",
        description="Path to the remap configuration file",
    )
