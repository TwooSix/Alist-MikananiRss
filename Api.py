import Config
import requests

def createApiHandler(domain):
    return ApiHandler(domain)

class ApiHandler():

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.0.1722.39',
        'Content-Type': 'application/json'
    }
    isLogin = False

    def __init__(self, domain:str) -> None:
        self.domain = domain
        

    def login(self, username:str, password:str) -> dict:
        """登录Alist并获取token"""

        api_url = f'https://{self.domain}/api/auth/login'
        body = {
            "username": username,
            "password": password
        }

        try:
            response = requests.request("POST", api_url, headers=self.headers, json=body)
        except Exception as e:
            raise Exception(f'Failed to connect {self.domain}:\n{e}')
        
        jsonData = response.json()
        if response.status_code != 200:
            raise Exception(jsonData)

        self.token = jsonData['data']['token']
        self.headers['Authorization'] = f'{self.token}'
        self.isLogin = True
        return jsonData

    def add_aria2(self, savePath:str, urls:list[str]) -> dict:
        assert self.isLogin, 'Please login first'
        api_url = f'https://{self.domain}/api/fs/add_aria2'
        body = {
            "path": savePath,
            "urls": urls
        }
        try:
            response = requests.request("POST", api_url, headers=self.headers, json=body)
        except Exception as e:
            return None
        return response.json()
