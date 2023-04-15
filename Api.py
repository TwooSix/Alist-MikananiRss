import Config
import requests

headers = {
   'Authorization': f'{Config.token}',
   'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.0.1722.39',
   'Content-Type': 'application/json'
}

def add_aria2(savePath:str, urls:list[str]) -> dict:
    api_url = f'https://{Config.domain}/api/fs/add_aria2'
    body = {
        "path": savePath,
        "urls": urls
    }
    response = requests.request("POST", api_url, headers=headers, json=body)
    return response.json()