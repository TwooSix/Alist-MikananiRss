import json

from openlist_ani.logger import logger
from ..models import ParsedFields, TitleParseResponse
from .client import LLMClient
from .json import parse_json_array_from_markdown
from .prompts import BATCH_SYSTEM_PROMPT, build_batch_user_message


async def parse_title_batch_via_llm(
    llm: LLMClient, titles: list[str]
) -> list[TitleParseResponse]:
    messages = [
        {"role": "system", "content": BATCH_SYSTEM_PROMPT},
        {"role": "user", "content": build_batch_user_message(titles)},
    ]
    try:
        content = await llm.complete_chat(messages)
        results = extract_batch_results(content, len(titles))
        if any(item.success for item in results):
            return results
        repair_messages = [
            {
                "role": "system",
                "content": BATCH_SYSTEM_PROMPT
                + "\nRepair the supplied invalid response. Return only the required JSON array.",
            },
            {
                "role": "user",
                "content": (
                    build_batch_user_message(titles)
                    + "\n\nInvalid response to repair:\n"
                    + content
                ),
            },
        ]
        repaired = await llm.complete_chat(repair_messages)
        return extract_batch_results(repaired, len(titles))
    except Exception as e:
        logger.warning(f"Batch LLM parsing failed: {e}")
        return [TitleParseResponse(success=False, error=str(e)) for _ in titles]


def extract_batch_results(
    content: str, expected_count: int
) -> list[TitleParseResponse]:
    json_str = parse_json_array_from_markdown(content)

    if not json_str:
        logger.warning(
            f"Batch LLM failed to return valid JSON array "
            f"(expected_count={expected_count})"
        )
        logger.debug(f"Batch LLM invalid output sample: {content[:500]}")
        return [
            TitleParseResponse(success=False, error="LLM returned no valid JSON array")
            for _ in range(expected_count)
        ]

    try:
        raw_items = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Batch JSON decode error: {e}")
        return [
            TitleParseResponse(success=False, error=f"JSON decode error: {e}")
            for _ in range(expected_count)
        ]

    if not isinstance(raw_items, list):
        logger.warning(f"Batch LLM returned non-list JSON: {type(raw_items)}")
        return [
            TitleParseResponse(success=False, error="LLM returned non-list JSON")
            for _ in range(expected_count)
        ]

    item_map: dict[int, dict] = {}
    for item in raw_items:
        if isinstance(item, dict) and "index" in item:
            item_map[item["index"]] = item

    return [
        _build_single_result(item_map.get(i + 1), i + 1) for i in range(expected_count)
    ]


def _build_single_result(item: dict | None, index: int) -> TitleParseResponse:
    if item and item.get("status") == "success":
        try:
            result = ParsedFields.model_validate(item)
            return TitleParseResponse(success=True, result=result)
        except Exception as e:
            logger.warning(f"Batch item {index} validation failed: {e}")
            return TitleParseResponse(success=False, error=f"Validation failed: {e}")

    reason = item.get("reason", "unknown") if item else "missing from response"
    logger.debug(f"Batch item {index} failed: {reason}")
    return TitleParseResponse(success=False, error=reason)
