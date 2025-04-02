import os
from enum import StrEnum
from functools import lru_cache


class PromptType(StrEnum):
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"


@lru_cache(maxsize=32)
def load_prompt(prompt_type: PromptType, prompt_name: str) -> str:
    """Load a prompt from a file"""
    if prompt_type == PromptType.JSON_OBJECT:
        prompt_dir = "json_object"
    elif prompt_type == PromptType.JSON_SCHEMA:
        prompt_dir = "json_schema"
    else:
        raise ValueError(f"Invalid prompt type: {prompt_type}")
    base_dir = os.path.join(os.path.dirname(__file__), prompt_dir)
    file_path = os.path.join(base_dir, f"{prompt_name}.txt")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Prompt file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    # Example usage
    try:
        prompt = load_prompt(PromptType.JSON_SCHEMA, "anime_name")
        print(prompt)
    except FileNotFoundError as e:
        print(e)
