# http_utils.py
from typing import Any, Dict

import aiohttp


async def send_request(
    method: str,
    url: str,
    headers: Dict[str, str],
    data: Any = None,
    json: Any = None,
) -> Dict[str, Any]:
    """
    Send an HTTP request and return the response data as a dictionary.

    Args:
        method (str): HTTP method (e.g., 'GET', 'POST', 'PUT')
        url (str): URL for the request
        headers (Dict[str, str]): Headers for the request
        data (Any, optional): Data to be sent in the request body. Defaults to None.
        json (Any, optional): JSON data to be sent in the request body. Defaults to None.
        files (Dict[str, Any], optional): Files to be sent in the request body. Defaults to None.

    Returns:
        Dict[str, Any]: Response data as a dictionary

    Raises:
        aiohttp.ClientResponseError: If the response status code is not 200
    """
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with getattr(session, method.lower())(
            url, headers=headers, data=data, json=json
        ) as response:
            response.raise_for_status()
            json_data = await response.json()
            if json_data["code"] != 200:
                msg = json_data.get("message", "Unknown error")
                raise aiohttp.ClientResponseError(
                    response.request_info,
                    response.history,
                    status=json_data["code"],
                    message=msg,
                    headers=response.headers,
                )
            return json_data["data"]
